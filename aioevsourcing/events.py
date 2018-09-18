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
import logging

from abc import ABC, abstractmethod

# dataclasses is a standard module in Python 3.7. Pylint doesn't know this.
# pylint: disable=wrong-import-order
from dataclasses import dataclass, field

# pylint: enable=wrong-import-order
from typing import (
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)
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
                raise ValueError(
                    "Empty topic set for event '{}'".format(repr(cls))
                )
            elif not isinstance(cls.topic, str):
                raise TypeError(
                    "{}: 'topic' must be a 'str', not '{}'.".format(
                        cls, type(cls.topic).__name__
                    )
                )
            else:
                cls.registry[cls.topic] = cls  # type: ignore


@dataclass
class Message:
    """Event bus message format."""

    aggregate_id: str
    event: Event


QueueItem = TypeVar("QueueItem")


@runtime
class MessageCodec(Generic[QueueItem], Protocol):
    """The message codec protocol, for encoding and decoding bus messages."""

    @staticmethod
    @abstractmethod
    def encode(message: Message) -> QueueItem:
        """Encode a message into a queue item data.

        The data format must be supported by the bus queue.

        Args:
            message (Message): A message.
        Returns:
            data of any queue-supported type
        """
        pass

    @staticmethod
    @abstractmethod
    def decode(item: QueueItem) -> Message:
        """Decode a queue item into a message.

        Args:
            data (Any): data from a queue item
        Returns:
            Message
        """
        pass


class PassthroughCodec(MessageCodec):
    """A passthrough codec, for cases when the queue supports python objects."""

    @staticmethod
    def encode(message: Message) -> Message:
        return message

    @staticmethod
    def decode(item: Message) -> Message:
        return item


class EventBus(collections.abc.AsyncIterator):
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
        codec: Union[Type[MessageCodec], MessageCodec] = PassthroughCodec,
        queue: Optional[asyncio.Queue] = None,
        context: Optional[Dict] = None,
    ) -> None:
        self._queue = asyncio.Queue() if queue is None else queue
        self._registry = registry
        self._codec = codec
        self._subscriptions: Dict[str, Set[Callable]] = {}
        self._context = {} if context is None else context
        self._listen_task: Optional[Task] = None

    async def __anext__(self) -> Message:
        if self._listen_task is None or self._listen_task.cancelled():
            raise StopAsyncIteration
        data = await self._queue.get()
        message = self._codec.decode(data)
        return message

    def close(self, timeout: int = 30) -> None:
        """Close the event bus.

        The event bus won't get new events from the queue.
        It will however put events generated by still running reactors in the
        queue.
        After the timeout, it will return, meaning the calling code might exit
        and cancel even shielded reactors.

        Args:
            timeout (int): Time after which this method returns.
        """
        if self._listen_task is not None:
            self._listen_task.cancel()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(asyncio.sleep(timeout))
            loop.run_until_complete(self._listen_task)

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
        message = Message(aggregate_id=aggregate_id, event=event)
        data = self._codec.encode(message)
        await self._queue.put(data)

    async def react(self, message: Message) -> None:
        """Run reactors with arguments (aggregate ID, event, context)

        Args:
            aggregate_id (str): An aggregate ID.
            event (Event): An event.
        """
        aggregate_id, event = message.aggregate_id, message.event
        subscriptions = self._subscriptions.get(event.topic, [])
        ctx = self._context
        asyncio.gather(
            *[reactor(aggregate_id, event, ctx) for reactor in subscriptions]
        )
        # self.acknowledge(event) to remove it from the retry mechanism of a
        # safe queue like an LPOPRPUSH Redis queue

    async def _event_listener(self) -> None:
        """The central event listener. Only used as a long running private task.

        See the 'listen' method for actual use.
        """
        logger.info("Listening for events...")
        try:
            async for message in self:
                logger.debug("Bus message: %r", message)
                # Shield reactors execution from listening task cancellation
                await asyncio.shield(self.react(message))
        except asyncio.CancelledError:
            logger.info(
                "Stop listening. %s messages remaining.",
                str(self._queue.qsize()),
            )

    def listen(self) -> None:
        """Shorthand to listen to the bus for events, dispatch them to reactors.
        """
        # should prevent running the listener twice
        loop = asyncio.get_event_loop()
        self._listen_task = loop.create_task(self._event_listener())


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


class DictEventStore(EventStore):
    """A concrete event store class, using a dict as event storage.

    Args:
        db (Dict): .
    """

    def __init__(self, db: Optional[Dict[str, List[Event]]] = None) -> None:
        self._db = {} if db is None else db

    async def load_stream(self, global_id: str) -> EventStream:
        events = self._db.get(global_id, [])
        # if not events:
        #     raise DataNotFoundError
        return EventStream(version=len(events), events=events)

    async def append_to_stream(
        self,
        global_id: str,
        events: List[Event],
        expect_version: Optional[int] = None,
    ) -> None:
        if not self._db.get(global_id):
            self._db[global_id] = events
        else:
            if (
                expect_version is not None
                and len(self._db[global_id]) is not expect_version
            ):
                raise ConcurrentStreamWriteError
            self._db[global_id].extend(events)
