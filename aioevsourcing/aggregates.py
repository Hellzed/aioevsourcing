"""aioevsourcing.aggregates

Provides a base aggregate class for an event sourcing application,
as well as a base repository class to handle saving/loading aggregates.
"""
import logging
import sys
import uuid
import warnings

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Optional, Tuple, Type

from aioevsourcing import commands, events

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name
if not sys.warnoptions:
    warnings.simplefilter("default")


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
        self._saved: bool = True
        if not isinstance(event_stream, events.EventStream):
            raise BadEventStreamError(event_stream)

        self._version = event_stream.version
        for event in event_stream.events:
            self.apply(event)

        self._changes: List[events.Event] = []

    def __del__(self) -> None:
        if not self._saved:
            warnings.warn(
                "Aggregate '{}' not saved before going out of scope".format(
                    repr(self)
                ),
                ResourceWarning,
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
    def saved(self) -> bool:
        """List of events as changes (since the aggregate was loaded)
        """
        return self._saved

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
        self,
        command: commands.Command,
        *args: commands.CmdArgs,
        **kwargs: commands.CmdKwargs,
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
            event = command(self, *args, **kwargs)
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
            raise
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


class BadEventStreamError(TypeError):
    """Raise this error when an event stream lacks version or event attributes
    """

    def __init__(self, stream: object) -> None:
        super().__init__(
            "Expected 'aioeventsourcing.events.EventStream' to initialise "
            "aggregate, '{}' given.".format(type(stream))
        )


class Repository(ABC):
    """Repository abstract base class.

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
        self,
        event_store: events.EventStore,
        event_bus: Optional[events.EventBus] = None,
    ) -> None:
        self._event_store = event_store
        self._event_bus = event_bus
        self._active_transactions: Dict[str, str] = {}

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
        event_stream = await self._event_store.load_stream(global_id)
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
            warnings.warn(
                "Nothing to save in repository '{}' for aggregate '{}', "
                "consider using '<repo>.load(aggregate_id)' directly for "
                "read-only access, and avoid saving the same aggregate twice.\n"
                "Note: 'execute_transaction()' auto-saves".format(
                    type(self), aggregate
                ),
                SyntaxWarning,
            )
            return
        await self._event_store.append_to_stream(
            aggregate.global_id,
            aggregate.changes,
            expect_version=aggregate.version,
        )
        if self._event_bus is not None:
            try:
                for event in aggregate.changes:
                    await self._event_bus.publish(aggregate.global_id, event)
            except AttributeError:
                logger.error(
                    "Cannot 'publish' aggregate %s saved events to bus %r. "
                    "No such method!",
                    aggregate,
                    self._event_bus,
                )
        if mark_saved:
            aggregate.mark_saved()

    def open_transaction(self, aggregate_id: Optional[str]) -> str:
        """Open a transaction on the repository, registered for an aggregate ID.

        Args:
            aggregate_id (str): The ID of the aggregate.

        Returns:
            transaction_id (str): The ID of the transaction.
        """
        transaction_id = str(uuid.uuid4())
        self._active_transactions[transaction_id] = aggregate_id or "anonymous"
        return transaction_id

    def close_transaction(self, transaction_id: str) -> None:
        """Close a transaction on the repository.

        Args:
            transaction_id (str): The ID of the transaction.
        """
        try:
            self._active_transactions.pop(transaction_id)
        except KeyError:
            pass

    @staticmethod
    def _format_transactions(transactions: Dict[str, str]) -> str:
        return "\n".join(
            [
                "Tansaction ID: '{}' on aggregate '{}'".format(*transaction)
                for transaction in transactions.items()
            ]
        )

    def close(self) -> None:
        """Warn if transactions are still active.

        Repository 'closing' is the best practice to get a log about aggregates
        that may have been partially processed in the event of a forced
        application shutdown.
        """
        if self._active_transactions:
            logger.warning(
                "Repository '%r' had active transactions on close:\n%s"
                "\nEvents may have fallen off the bus!",
                self,
                self._format_transactions(self._active_transactions),
            )


@asynccontextmanager
async def execute_transaction(
    repository: Repository, global_id: Optional[str] = None
) -> AsyncIterator[Aggregate]:
    """An asynchronous context manager to use a repository.

    Takes a repository, yields an aggregate.
    If no aggregate ID is provided, it will create a new one.
    """
    try:
        aggregate = None
        transaction_id = repository.open_transaction(global_id)
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
            "'aioeventsourcing.aggregates.Repository'.",
            repository,
        )
        raise
    # handle concurrent write error here, probably reraise so calling coro will
    # recalculate changes. Or not?
    finally:
        repository.close_transaction(transaction_id)
