"""aioevsourcing.aggregates

Provides a base aggregate class for an event sourcing application,
as well as a base repository class to handle saving/loading aggregates.
"""
import collections
import logging

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Dict, List, Tuple, Type

from aioevsourcing import commands, events

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


class Aggregate(ABC):
    """Aggregate abstract base class.

    Subclass to create your own aggregate.

    As this is an event sourcing application, the object is built by replaying
    the chain of events leading to current state.

    For convenience, use as a dataclass without init.

    Args:
        event_stream (events.EventStream): An event stream to replay.

    Attributes:
        event_types (Tuple[Type[events.Event], ...]): A list of event types
            supported by the aggregate.
        version (int): The current version number of the agregate.
            This value is obtained from the event stream used to build
            the aggregate and doesn't change afterwards.
        changes (List[events.Event]): A list of events used to keep track of
            changes to the current version of the aggregate. Starts empty after
            init.
        global_id (str): All aggregates must specify a global ID.
            It is required for storage and event publishing.

    Examples:
    >>> from dataclasses import dataclass
    >>> @dataclass(init=False)
    ... class MyAggregate(Aggregate):
    ...     event_types = (events.Event,)
    """

    global_id: str

    def __init_subclass__(cls, *_: Tuple) -> None:
        if not isinstance(cls.event_types, tuple):
            raise TypeError(
                "{}: 'event_types' must be a tuple of types, not '{}'.".format(
                    cls, type(cls.event_types)
                )
            )

    def __init__(
        self, event_stream: events.EventStream = events.EventStream()
    ) -> None:
        if not isinstance(event_stream, events.EventStream):
            raise BadEventStreamError(event_stream)

        self._version = event_stream.version
        for event in event_stream.events:
            self.apply(event)

        self._saved = True
        self._changes: List = []

    def __del__(self) -> None:
        if not self._saved:
            logger.warning(
                "Aggregate '%r' not saved before going out of scope", self
            )

    @property
    @abstractmethod
    def event_types(self) -> Tuple[Type[events.Event], ...]:
        """Tuple of supported Event types
        """
        pass

    @property
    def version(self) -> int:
        """Current aggregate version (as of when the aggregate was loaded)
        """
        return self._version

    @property
    def changes(self) -> List[events.Event]:
        """List of events as changes (since the aggregate was loaded)
        """
        return self._changes

    def apply(self, event: events.Event) -> None:
        """Mutate the aggregate by applying an event.

        To enhance modularity, the event has to define it's own apply method to
        ensure its ability apply itself to the calling aggregate.

        Args:
            event (Callable): The event to apply.

        Raises:
            EventNotSupportedError: The event is not in the allowed event_types,
            or a subclass of one of the allowed event_types.
        """
        if not isinstance(event, self.event_types):
            raise EventNotSupportedError(self, event)
        try:
            event.apply_to(self)
        except (AttributeError, NotImplementedError):
            logger.error("Event '%r' must implement an 'apply' method.", event)

    def execute(
        self, command: commands.Command, *args: Tuple, **kwargs: Dict
    ) -> None:
        """Call a command to mutate the aggregate.

        Internally the command must issue an event that will be passed to the
        aggregate's apply method.
        If the command doesn't return an event, or fails , the aggregate is not
        mutated.

        Args:
            command: A command to execute. *args and **kwargs are passed to this
                command.

        Raises:
            RuntimeError: Any error that happens inside the command.
                Raising these errors enables custom error handling in the
                transaction script currently managing the aggregate.
        """
        try:
            # Is mypy confused by the __call__ method in protocol?
            event = command(self, *args, **kwargs) # type: ignore
            if not isinstance(event, events.Event):
                raise commands.MustReturnEventError(command)
            self.apply(event)
            self._changes.append(event)
            self._saved = False
        except (
            commands.MustReturnEventError,
            EventNotSupportedError,
        ) as cmd_error:
            logger.error(
                "%s: %s Aggregate left unchanged.",
                type(self).__name__,
                str(cmd_error),
            )
        except Exception as cmd_error:
            logger.error(
                "%s: Command '%s.%s' failed. Aggregate left unchanged.",
                type(self).__name__,
                command.__module__,
                command.__name__,
            )
            raise

    def mark_saved(self) -> None:
        """Mark the aggregate as "saved".

        This disables the warning otherwise logged if an aggregate goes out of
        scope without being marked as saved first.
        """
        self._saved = True
        self._version += len(self._changes)
        self._changes = []


class EventNotSupportedError(TypeError):
    """Raise this error when a callable doesn't support given event type
    """

    def __init__(self, aggregate: Aggregate, event: events.Event) -> None:
        super().__init__(
            "{} doesn't support event {}. Supported types are {}.".format(
                type(aggregate), event, aggregate.event_types
            )
        )


class BadEventStreamError(AttributeError):
    """Raise this error when an event stream lacks version or event attributes
    """

    def __init__(self, stream: object) -> None:
        super().__init__(
            "Expected 'aioeventsourcing.events.EventStream' to initialise "
            "aggregate, '{}' given.".format(type(stream))
        )


class AggregateRepository(ABC):
    """AggregateRepository abstract base class.

    Subclass and add an `aggregate` class property to create your own
    repository.

    Args:
        event_bus (events.EventBus): Where events are published once stored.
        event_store (events.EventStore): Where events are stored.

    Attributes:
        aggregate (Type[aggregates.Aggregate]): The type of the aggregates to
            save/load to/from this repository.
    """

    def __init__(
        self, event_store: events.EventStore, event_bus: events.EventBus = None
    ) -> None:
        self.event_store = event_store
        self.event_bus = event_bus

    @property
    @abstractmethod
    def aggregate(self) -> Type[Aggregate]:
        """The aggregate type to load/save from this repository.
        """
        pass

    async def load(self, global_id: str) -> Aggregate:
        """Load an aggregate by ID.

        Args:
            global_id (str): The ID of the aggregate to load.

        Returns:
            Aggregate
        """
        # handle the AggregateNotFoundError case
        event_stream = await self.event_store.load_stream(global_id)
        return self.aggregate(event_stream)

    async def save(
        self, aggregate: Aggregate, mark_saved: bool = True
    ) -> None:
        """Save an aggregate and publish changes to the event bus if present.

        Also marks the aggregate as saved by default.

        Args:
            aggregate (aggregates.Aggregate): The ID of the aggregate to save.
        """
        if not aggregate.changes:
            logger.info(
                "Nothing to save in repository '%s' for aggregate '%r'",
                type(self),
                aggregate,
            )
            return
        await self.event_store.append_to_stream(
            aggregate.global_id,
            aggregate.changes,
            expect_version=aggregate.version,
        )
        if self.event_bus is not None:
            try:
                for event in aggregate.changes:
                    await self.event_bus.publish(aggregate.global_id, event)
            except AttributeError:
                logger.error(
                    "Cannot 'publish' aggregate %s saved events to bus %r. "
                    "No such method!",
                    aggregate,
                    self.event_bus,
                )
        if mark_saved:
            aggregate.mark_saved()


@asynccontextmanager
async def execute_transaction(
    repository: AggregateRepository, global_id: str = None
) -> collections.abc.AsyncGenerator:
    """An asynchronous context manager to use a repository.

    Takes a repository, yields an aggregate.
    If no aggregate ID is provided, it will create a new one
    """
    try:
        if global_id is not None:
            aggregate = await repository.load(global_id)
        else:
            aggregate = repository.aggregate()
        yield aggregate
        if aggregate is not None:
            await repository.save(aggregate)
    except AttributeError:
        logger.error(
            "Repository '%r' must implement have an 'aggregate' attribute and "
            "define 'load' and 'save' methods. A repository type may be "
            "obtained by subclassing "
            "'aioeventsourcing.aggregates.AggregateRepository'.",
            repository,
        )
        raise
