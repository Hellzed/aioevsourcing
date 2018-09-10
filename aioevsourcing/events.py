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
from asyncio import Task

import collections
import inspect
import json
import logging

from abc import ABC, abstractmethod

# dataclasses is a standard module in Python 3.7. Pylint doesn't know this.
# pylint: disable=wrong-import-order
from dataclasses import asdict, dataclass, field

# pylint: enable=wrong-import-order
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type
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

    @property
    @abstractmethod
    def topic(self) -> str:
        """The event topic used for configuration and bus operations"""
        pass

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

    def __init_subclass__(cls, *_: Tuple) -> None:
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
                cls.registry[cls.topic] = cls  # type: ignore


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
        registry: EventRegistry,
        queue: asyncio.Queue = asyncio.Queue(),
        context: Optional[Dict] = None,
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop(),
    ) -> None:
        self._queue = queue
        self._registry = registry
        self._subscriptions: Dict[str, Set[Callable]] = {}
        self._context = context
        self._loop = loop
        self._closed = True
        self._listen_task: Optional[Task] = None

    async def __anext__(self) -> Tuple:
        if self._closed:
            raise StopAsyncIteration
        message = await self._queue.get()
        return self._decode(message)

    async def close(self, timeout: int = 30) -> None:
        """Close the event bus.

        The event bus won't get new events from the queue.
        It will however put events generated by still running reactors in the
        queue.
        After the timeout, it will return, meaning the calling code might exit
        and cancel even shielded reactors.

        Args:
            timeout (int): Time after which this method returns.
        """
        self._closed = True
        if self._listen_task is not None:
            self._listen_task.cancel()
            await asyncio.sleep(timeout)
            await self._listen_task

    def subscribe(self, reactor: Callable, *topics: str) -> None:
        """Subscribe a reactor to a topic.

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

    async def publish(self, aggregate_id: str, event: Event) -> None:
        """Publish an event under an aggregate_id in the bus.

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        """
        message = self._encode(aggregate_id, event)
        await self._queue.put(message)

    async def react(self, aggregate_id: str, event: Event) -> None:
        """Run reactors with arguments (aggregate ID, event, context)

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
        # self.acknowledge(event) to remove it from the retry mechanism of a
        # safe queue like an LPOPRPUSH Redis queue

    async def _event_listener(self) -> None:
        """The central event listener. Only used as a long running private task.

        See the 'listen' method for actual use.
        """
        logger.info("Listening for events...")
        try:
            async for aggregate_id, event in self:
                logger.debug("Bus message: %s, %r", aggregate_id, event)
                # Shield reactors execution from listening task cancellation
                await asyncio.shield(self.react(aggregate_id, event))
        except asyncio.CancelledError:
            logger.info(
                "Stop listening. %s messages remaining.",
                str(self._queue.qsize()),
            )

    def listen(self) -> None:
        """Shorthand to listen to the bus for events, dispatch them to reactors.
        """
        self._closed = False
        self._listen_task = self._loop.create_task(self._event_listener())

    @abstractmethod
    def _encode(self, aggregate_id: str, event: Event) -> str:
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
    def _decode(self, message: str) -> tuple:
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

    def __init__(self, serializer=json, **kwargs: Any) -> None:  # type: ignore
        super().__init__(**kwargs)
        self.json = serializer

    def _encode(self, aggregate_id: str, event: Event) -> str:
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

    def _decode(self, message: object) -> Tuple[str, Event]:
        """Decode a JSON queue message into a tuple of (aggregate ID, event).

        Args:
            message (str): a message from the queue
        Returns:
            Tuple[str, Event]
        """
        data = self.json.loads(message)
        return (
            data["aggregate_id"],
            self._registry[data["event"]["topic"]](  # type: ignore
                **data["event"]["data"]
            ),
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
    async def load_stream(self, global_id: str) -> EventStream:
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
