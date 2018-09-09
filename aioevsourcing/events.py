"""aioevsourcing.events

Provides base event, event bus and event store classes for an event sourcing
application.

Event stream, event registry and a an event bus implementing json transport
classes are also provided.

Self registering events may be useful when using an event registry.

When implementing an event store, the concurrent write error is used to
customise write behaviour.
"""
import asyncio
import collections
import inspect
import json
import logging

from abc import ABC, abstractmethod

# dataclasses is a standard module in Python 3.7. Pylint doesn't know this.
# pylint: disable=wrong-import-order
from dataclasses import asdict, dataclass, field

# pylint: enable=wrong-import-order
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type
from typing_extensions import Protocol, runtime

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


@runtime
class Event(Protocol):
    """Event protocol.

    Subclass to create your own event, or just provide an object compatible with
    the protocol.

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

    topic: str = None

    @abstractmethod
    def apply_to(self, aggregate: object) -> None:
        """Mutate an aggregate by applying the event.

        To enhance modularity, the aggregate calls this method through its own
        `apply` when passed a supported event.

        Args:
            aggregate (object): The aggregate to which apply the
                event.
        """
        pass


@dataclass
class EventStream:
    """An event stream is a versioned (ordered) list of events.

    It is used to save and replay, or otherwise transport events.

    Args:
        version (int): An version number. Defaults to 0.
        events (List[Event]): A list of Events. Default to an empty list.
    """

    version: int = 0
    events: List[Event] = field(default_factory=list)


class EventRegistry(Dict[str, Type[Event]]):
    """An event registry holding event types as values indexed by string keys.

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

    registry: EventRegistry = EventRegistry()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            # pylint: disable=unsupported-assignment-operation
            if not cls.topic:
                logger.warning("No topic set for event %r", cls)
            elif not isinstance(cls.topic, str):
                raise TypeError(
                    "{}: 'topic' must be a 'str', not '{}'.".format(
                        cls, type(cls.topic).__name__
                    )
                )
            else:
                cls.registry[cls.topic] = cls


class EventBus(collections.abc.AsyncIterator, ABC):
    """Event bus abstract base class.

    Subclass to create your own event bus.

    This is an async iterator, the `async for ... in self`, with `listen()` as a
    shorthand, allows to listen asynchronously for events in the bus.

    Args:
        registry (EventRegistry): The event registry from which to lookup the
            event types supported by the bus.
        queue (asyncio.Queue): The queue to put events in, and to get them from.

    Examples:
    >>> class MyEventBus(EventBus):
    ...     # implement concrete `_encode` and `_decode`
    >>> event_bus = MyEventBus(EventRegistry({"topic": MyEvent}))
    >>> listen_task = loop.create_task(event_bus.listen())
    """

    def __init__(
        self,
        registry: EventRegistry = None,
        queue: asyncio.Queue = asyncio.Queue(),
        context: Any = None,
        loop: asyncio.AbstractEventLoop = None,
    ) -> None:
        self._queue = queue
        self._registry = registry
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._context = context
        self._loop = loop if loop is not None else asyncio.get_event_loop()
        self._closed = False
        self._listen_task = None

    async def __anext__(self):
        if self._closed:
            raise StopAsyncIteration
        message = await self._queue.get()
        return self._decode(message)

    async def close(self, timeout=5):
        self._closed = True
        if self._listen_task is not None:
            self._listen_task.cancel()
            await asyncio.sleep(timeout)
            await self._listen_task

    def subscribe(self, reactor, *topics):
        """Subscribe a reactor to a topic

        Args:
            reactor: A reactor
            topic (str): A topic.
        """
        for topic in topics:
            try:
                self._subscriptions[topic].add(reactor)
            except KeyError:
                if topic not in list(self._registry):
                    logger.warning(
                        "Subscribing reactor '%s' to unknown topic "
                        " '%s'. Event declaring this topic might be missing "
                        "from the event repository.",
                        reactor.__name__,
                        topic,
                    )
                self._subscriptions[topic] = {reactor}

    async def publish(self, aggregate_id: str, event: Event):
        """Publish an event under an aggregate_id in the bus.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        """
        message = self._encode(aggregate_id, event)
        await self._queue.put(message)

    async def react(self, aggregate_id, event: Event):
        """Publish an event under an aggregate_id in the bus.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        """
        subscriptions = self._subscriptions.get(event.topic, [])
        asyncio.gather(
            *[
                reactor(aggregate_id, event, self._context)
                for reactor in subscriptions
            ]
        )

    async def _event_listener(self):
        print("Listening...")
        try:
            async for aggregate_id, event in self:
                print("Bus message:", aggregate_id, event)
                await asyncio.shield(self.react(aggregate_id, event))
        except asyncio.CancelledError:
            print(
                "Stop listening. {} messages remaining.".format(
                    self._queue.qsize()
                )
            )

    def listen(self):
        """Shorthand to listen to the bus for events, dispatch them to reactors.
        """
        self._listen_task = self._loop.create_task(self._event_listener())

    @abstractmethod
    def _encode(self, aggregate_id: str, event: Event) -> Any:
        """Encode an aggregate ID and an event into a message.

        The message format must be supported by the bus queue.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        Returns:
            a message of any queue-supported type
        """
        pass

    @abstractmethod
    def _decode(self, message: Any) -> tuple:
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
        """Encode an aggregate ID and an event into a JSON message for the bus.

        Args:
            message (str): a message from the queue
        Returns:
            Tuple[str, Event]
        """
        return self.json.dumps(
            {
                "aggregate_id": aggregate_id,
                "event": {"topic": event.topic, "data": asdict(event)},
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
            self._registry[data["event"]["topic"]](**data["event"]["data"]),
        )


class ConcurrentStreamWriteError(RuntimeError):
    """Raise this error when trying to write an event stream to a store, but
    expected version doesn't match (a more recent version of the stream already
    exists in the store).
    """

    def __init__(
        self, global_id: str, expected_version: int, found_version: int
    ) -> None:
        super().__init__(
            "Concurrency error: Aggregated ID '{}', cannot append events to "
            "expected version {}, found version {}.".format(
                global_id, expected_version, found_version
            )
        )


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
        global_id: str,
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
