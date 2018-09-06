"""aioevsourcing.events

Provides base event, event bus and event store classes for an event sourcing
application.

Event stream, event registry and a an event bus implementing json transport
classes are also provided.

Self registering events may be useful when using an event registry.

When implementing an event store, the concurrent write error is used to
customise write behaviour.
"""
import json
import logging

from abc import ABC, abstractmethod
from asyncio import CancelledError, gather, Queue
from collections.abc import AsyncIterator
from inspect import isabstract
from typing import Callable, Dict, List, Optional, Type
from dataclasses import asdict, dataclass, field

LOGGER = logging.getLogger(__name__)


class Event(ABC):
    """Event abstract base class.

    Subclass to create your own event.

    For convenience, use as a frozen dataclass.

    Attributes:
        topic (str): A topic under which the event can be registered and
            and published on a bus.

    Examples:
    >>> from dataclasses import dataclass
    >>> @dataclass(frozen=True)
    ... class MyEvent(Event):
    ...     example_prop: str = "example value"
    """

    topic = None

    @abstractmethod
    def apply(self, aggregate) -> None:
        """Mutate an aggregate by applying the event.

        To enhance modularity, the aggregate calls this method through its own
        `apply` when passed a supported event.

        Args:
            aggregate (Aggregate): The aggregate to which apply the event.
        """
        pass


@dataclass
class EventStream:
    """An event stream is a versioned (oredered) list of events.

    It is used to save and replay, or otherwise transport events.

    Args:
        version (int): An version number. Defaults to 0.
        events (List[Event]): A list of Events. Default to an empty list.
    """

    version: int = 0
    events: List[Event] = field(default_factory=list)


class EventRegistry(Dict[str, Type[Event]]):
    """An event registry, holding event types as values associated to string
        keys.

    Behaves as a normal dict, but useful for clarity and static type checking.
    """

    pass


class SelfRegisteringEvent(Event, ABC):
    """Self-registering event abstract base class.

    Subclass to create your own self-registering event.

    Attributes:
        registry (EventRegistry): An event registry. Defaults to an empty event
            registry.
    """

    registry = EventRegistry()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not isabstract(cls):
            # pylint: disable=unsupported-assignment-operation
            if not cls.topic:
                LOGGER.warning("No topic set for event %r", cls)
            elif not isinstance(cls.topic, str):
                raise TypeError(
                    "{}: 'topic' must be a 'str', not '{}'.".format(
                        cls, type(cls.topic).__name__
                    )
                )
            else:
                cls.registry[cls.topic] = cls


class EventBus(AsyncIterator, ABC):
    """Event bus abstract base class.

    Subclass to create your own event bus.

    This is an async iterator, the `async for ... in self`, with `listen()` as a
    shorthand, allows to listen asynchronously for events in the bus.

    Args:
        registry (EventRegistry): The event registry from which to lookup the
            event types supported by the bus.
        queue (Queue): The queue to put events in, and to get them from.

    Examples:
    >>> class MyEventBus(EventBus):
    ...     # implement concrete `_encode` and `_decode`
    >>> event_bus = MyEventBus(EventRegistry({"topic": MyEvent}))
    >>> listen_task = loop.create_task(event_bus.listen())
    """

    def __init__(
        self, registry: EventRegistry = None, queue: Queue = Queue()
    ) -> None:
        self._queue = queue
        self._registry = registry
        self._subscriptions: Dict[str, List[Callable]] = {}

    async def __anext__(self):
        message = await self._queue.get()
        return self._decode(message)

    def subscribe(self, reactor, topic):
        try:
            self._subscriptions[topic].append(reactor)
        except KeyError:
            self._subscriptions[topic] = [reactor]

    async def publish(self, aggregate_id, event):
        """Publish an event under an aggregate_id in the bus.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        """
        message = self._encode(aggregate_id, event)
        await self._queue.put(message)

    async def listen(self):
        """Shorthand to listen for events in the bus and dispatch them to
            reactors.
        """
        try:
            print("Listening...")
            async for aggregate_id, event in self:
                print("Bus message:", aggregate_id, event)
                subscriptions = self._subscriptions.get(
                    event.__class__.__name__, []
                )
                await gather(
                    *[reactor(aggregate_id) for reactor in subscriptions]
                )

        except CancelledError:
            print(
                "Stop listening. {} messages remaining.".format(
                    self._queue.qsize()
                )
            )

    @abstractmethod
    def _encode(self, aggregate_id, event):
        """Encode an aggregate ID and an event into a message format supported
            by the bus queue.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        Returns:
            a message of any queue-supported type
        """
        pass

    @abstractmethod
    def _decode(self, message):
        """Decode a queue message into a tuple of (aggregate ID, event).

        Args:
            message (Any): a message from the queue
        Returns:
            Tuple[str, Event]
        """
        pass


class JsonEventBus(EventBus):
    """A concrete event bus class, using JSON encoded messages in the queue.

    Args:
        json: A JSON serializer.
    """

    def __init__(self, serializer=json, **kwargs):
        super().__init__(**kwargs)
        self.json = serializer

    def _encode(self, aggregate_id, event):
        """Encode an aggregate ID and an event into a JSON message format for
        the bus queue.

        Args:
            message (str): a message from the queue
        Returns:
            Tuple[str, Event]
        """
        return self.json.dumps(
            {
                "aggregate_id": aggregate_id,
                "event": {
                    "type": event.__class__.__name__,
                    "data": asdict(event),
                },
            }
        )

    def _decode(self, message):
        """Decode a JSON queue message into a tuple of (aggregate ID, event).

        Args:
            message (str): a message from the queue
        Returns:
            Tuple[str, Event]
        """
        data = self.json.loads(message)
        return (
            data["aggregate_id"],
            self._registry[data["event"]["type"]](**data["event"]["data"]),
        )


class ConcurrentStreamWriteError(RuntimeError):
    """Raise this error when trying to write an event stream to a store, but
    expected version doesn't match (a more recent version of the stream already
    exists in the store).
    """

    pass


class EventStore(ABC):
    """Event store abstract base class. Subclass to create your own event store.
    """

    @abstractmethod
    async def load_stream(self, global_id) -> EventStream:
        """Load an event stream by aggregate ID from the store.

        Args:
            global_id (str): An aggregate ID.
        Returns:
            EventStream
        """
        pass

    @abstractmethod
    async def append_to_stream(
        self,
        global_id,
        events: List[Event],
        expect_version: Optional[int] = None,
    ) -> None:
        """Append events to a stream into the store by aggregate ID.

        Args:
            global_id (str): An aggregate ID.
            events (List[Event]): A list of Events.
            expect_version (Optional[int]): If present, the expected version.
                This version must match for the events to be appended to the
                stream.
        """
        pass
