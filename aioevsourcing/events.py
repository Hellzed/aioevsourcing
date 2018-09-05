import json

from abc import ABC, abstractmethod
from asyncio import CancelledError, Queue
from collections.abc import AsyncIterator
from inspect import isabstract
from typing import Dict, List, Optional, Type
from dataclasses import asdict, dataclass, field


class Event(ABC):
    @abstractmethod
    def apply(self, aggregate) -> None:
        pass


@dataclass
class EventStream:
    version: int
    events: List[Event] = field(default_factory=list)


class EventRegistry(Dict[str, Type[Event]]):
    pass


class SelfRegisteringEvent(Event, ABC):
    registry = EventRegistry()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not isabstract(cls):
            # pylint: disable=unsupported-assignment-operation
            cls.registry[cls.__name__] = cls


class ConcurrentStreamWriteError(RuntimeError):
    pass


class EventBus(AsyncIterator, ABC):
    def __init__(
        self, registry: EventRegistry = None, queue: Queue = Queue()
    ) -> None:
        self._queue = queue
        self._registry = registry

    async def __anext__(self):
        message = await self._queue.get()
        return self._decode(message)

    async def publish(self, aggregate_id, event):
        message = self._encode(aggregate_id, event)
        await self._queue.put(message)

    async def listen(self):
        try:
            print("Listening...")
            async for message in self:
                print("Bus message:", message)
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
