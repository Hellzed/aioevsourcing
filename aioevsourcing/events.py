import json
import logging

from abc import ABC, abstractmethod
from asyncio import CancelledError, gather, Queue
from collections.abc import AsyncIterator
from inspect import isabstract
from typing import Callable, Dict, List, Optional, Type
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


class Event(ABC):
    @abstractmethod
    def apply(self, aggregate) -> None:
        pass


@dataclass
class EventStream:
    version: int = 0
    events: List[Event] = field(default_factory=list)


class EventRegistry(Dict[str, Type[Event]]):
    pass


class SelfRegisteringEvent(Event, ABC):
    registry = EventRegistry()
    topic = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not isabstract(cls):
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


class EventBus(AsyncIterator, ABC):
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
        message = self._encode(aggregate_id, event)
        await self._queue.put(message)

    async def listen(self):
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
        pass

    @abstractmethod
    def _decode(self, message):
        pass


class JsonEventBus(EventBus):
    def __init__(self, serializer=json, **kwargs):
        super().__init__(**kwargs)
        self.json = serializer

    def _encode(self, aggregate_id, event):
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
        data = self.json.loads(message)
        return (
            data["aggregate_id"],
            self._registry[data["event"]["type"]](**data["event"]["data"]),
        )


class ConcurrentStreamWriteError(RuntimeError):
    pass


class EventStore(ABC):
    @abstractmethod
    async def load_stream(self, global_id) -> EventStream:
        pass

    @abstractmethod
    async def append_to_stream(
        self,
        global_id,
        events: List[Event],
        expect_version: Optional[int] = None,
    ) -> None:
        pass
