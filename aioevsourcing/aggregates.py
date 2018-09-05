"""
"""
import logging

from abc import ABC, abstractmethod
from typing import Awaitable, List
from uuid import uuid4

from .commands import ConcurrentCommandsError, MustReturnEventError
from .events import Event, EventBus, EventStream, EventStore


class EventNotSupportedError(TypeError):
    """Raise this error when a callable doesn't support given Event type
    """

    def __init__(self, aggregate, event) -> None:
        super().__init__(
            "{} doesn't support event {}. Supported types are {}".format(
                aggregate, event, aggregate.event_types
            )
        )


class Aggregate(ABC):
    """The Aggregate abstract base class. Subclass to create your own aggregate.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not isinstance(cls.event_types, tuple):
            raise TypeError(
                "{}: 'event_types' must be a tuple of types, not {}.".format(
                    cls, type(cls.event_types)
                )
            )

    def __init__(self, event_stream: EventStream = None) -> None:
        if event_stream is not None:
            self._version = event_stream.version
            for event in event_stream.events:
                self.apply(event)
        else:
            self._version = 0
            self.global_id = str(uuid4())

        self._command_running = False
        self._saved = True
        self._changes: List[Event] = []

    def __enter__(self):
        try:
            self.lock()
            return self
        except ConcurrentCommandsError:
            logging.error("Do not try to run commands concurrently")
            raise

    def __exit__(self, *args):
        self.unlock()
        return True

    def __del__(self):
        if not self._saved:
            print("Warning: aggregate not saved before going out of scope")

    @property
    @abstractmethod
    def event_types(self):
        """Supported Event types
        """
        pass

    @property
    def version(self):
        """Current aggregate version (as of when the aggregate was loaded)
        """
        return self._version

    @property
    def changes(self):
        """List of changes (since the aggregate was loaded)
        """
        return self._changes

    def mark_saved(self):
        self._saved = True

    def apply(self, event: Event) -> None:
        """Call the Event's apply method to mutate the aggregate.
        """
        if not isinstance(event, self.event_types):
            raise EventNotSupportedError
        event.apply(self)

    async def execute(self, command, *args, unsafe=False, **kwargs) -> None:
        """Call the Command, which will mutate the aggregate.
        """
        try:
            if not unsafe:
                self.lock()
            event = await command(self, *args, **kwargs)
            if not isinstance(event, Event):
                raise MustReturnEventError
            self.apply(event)
            self.changes.append(event)
            self._saved = False
        except RuntimeError:
            print("bad stuff happened during command")
            raise
        finally:
            self.unlock()

    def lock(self):
        """Lock the aggregate to ensure only one command is running at a time.
        """
        if self._command_running:
            raise ConcurrentCommandsError
        self._command_running = True

    def unlock(self):
        """Unlock the aggregate.
        """
        self._command_running = False


class AggregateRepository(ABC):
    def __init__(
        self, event_store: EventStore, event_bus: EventBus = None
    ) -> None:
        self.event_store = event_store
        self.event_bus = event_bus

    @property
    @abstractmethod
    def aggregate(self):
        pass

    async def load(self, global_id: str) -> Awaitable[Aggregate]:
        event_stream = await self.event_store.load_stream(global_id)
        return self.aggregate(event_stream)

    async def save(self, aggregate: Aggregate) -> None:
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
                logging.error(
                    "Cannot publish saved events to bus %r. No such method!",
                    self.event_bus,
                )
        aggregate.mark_saved()
