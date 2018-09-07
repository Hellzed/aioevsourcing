"""aioevsourcing.aggregates

Provides a base aggregate class for an event sourcing application,
as well as a base repository class to handle saving/loading aggregates.
"""
import logging

from abc import ABC, abstractmethod
from typing import Callable, List

from aioevsourcing import commands

LOGGER = logging.getLogger(__name__)


class Aggregate(ABC):
    """Aggregate abstract base class.

    Subclass to create your own aggregate.

    As this is an event sourcing application, the object is build by replaying
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
    ...     event_types = (Callable,)
    """

    global_id: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.event_types, tuple):
            raise TypeError(
                "{}: 'event_types' must be a tuple of types, not '{}'.".format(
                    cls, type(cls.event_types)
                )
            )

    def __init__(self, event_stream=None) -> None:
        self._version = 0

        if event_stream is not None:
            try:
                self._version = event_stream.version
                for event in event_stream.events:
                    self.apply(event)
            except AttributeError:
                raise BadEventStreamError(event_stream)

        self._saved = True
        self._changes: List = []

    def __del__(self):
        if not self._saved:
            LOGGER.warning(
                "Aggregate '%r' not saved before going out of scope", self
            )

    @property
    @abstractmethod
    def event_types(self):
        """List of supported Event types
        """
        pass

    @property
    def version(self):
        """Current aggregate version (as of when the aggregate was loaded)
        """
        return self._version

    @property
    def changes(self):
        """List of events as changes (since the aggregate was loaded)
        """
        return self._changes

    def apply(self, event) -> None:
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
            LOGGER.error("Event '%r' must implement an 'apply' method.", event)

    def execute(self, command, *args, **kwargs) -> None:
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
            if not hasattr(event, "apply_to"):
                raise commands.MustReturnEventError(command)
            self.apply(event)
            self.changes.append(event)
            self._saved = False
        except (
            commands.MustReturnEventError,
            EventNotSupportedError,
        ) as cmd_error:
            LOGGER.error(
                "%s: %s Aggregate left unchanged.",
                type(self).__name__,
                str(cmd_error),
            )
        except Exception as cmd_error:
            LOGGER.error(
                "%s: Command '%s.%s' failed. Aggregate left unchanged.",
                type(self).__name__,
                command.__module__,
                command.__name__,
            )
            raise

    def mark_saved(self):
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

    def __init__(self, aggregate: Aggregate, event: Callable) -> None:
        super().__init__(
            "{} doesn't support event {}. Supported types are {}".format(
                aggregate, event, aggregate.event_types
            )
        )


class BadEventStreamError(AttributeError):
    """Raise this error when an event stream lacks version or event attributes
    """

    def __init__(self, stream: object) -> None:
        super().__init__(
            "{} lacks 'version' and/or 'event' attributes and can't be read by "
            "the aggregate. A readable event stream type may be obtained by "
            "subclassing 'aioeventsourcing.events.EventStream'.".format(
                type(stream)
            )
        )
