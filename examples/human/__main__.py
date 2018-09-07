from abc import ABC
from asyncio import get_event_loop, sleep

# pylint: disable=wrong-import-order
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from aioevsourcing.aggregates import Aggregate, AggregateRepository
from aioevsourcing.commands import Command
from aioevsourcing.events import (
    Event,
    JsonEventBus,
    EventStore,
    EventStream,
    ConcurrentStreamWriteError,
    SelfRegisteringEvent,
)

db: dict = {}


class Status(str, Enum):
    UNKNOWN = "unknown"
    ALIVE = "alive"
    DEAD = "dead"


class HumanCommand(Command, ABC):
    pass


class HumanEvent(SelfRegisteringEvent, ABC):
    pass


@dataclass(init=False)
class Human(Aggregate):
    event_types = (HumanEvent,)

    global_id: str
    name: str
    status: Status = Status.UNKNOWN
    age: int = 0


# pylint: disable=arguments-differ
@dataclass(frozen=True)
class Born(HumanEvent):
    topic = "human.born"

    name: str
    status: Status = Status.ALIVE

    def apply(self, human: Human) -> None:
        human.name = self.name
        human.status = self.status
        print(
            "{} is now {}. Hello {}, welcome into this world!".format(
                human.name, human.status.value, human.name
            )
        )


def birth(_, name) -> Event:
    # print("Giving birth to a new human. His name will be {}!".format(name))
    return Born(name=name)


@dataclass(frozen=True)
class Renamed(HumanEvent):
    name: str

    def apply(self, aggregate: Human) -> None:
        aggregate.name = self.name


@dataclass(frozen=True)
class TimePassed(HumanEvent):
    years: int

    def apply(self, aggregate: Human) -> None:
        aggregate.age += self.years


@dataclass(frozen=True)
class Died(HumanEvent):
    status: Status = Status.DEAD

    def apply(self, aggregate: Human) -> None:
        aggregate.status = self.status
        print(
            "{} is now {}. Goodbye {}, you will be sorely missed!".format(
                aggregate.name, aggregate.status.value, aggregate.name
            )
        )


class HumanRepository(AggregateRepository):
    aggregate = Human


class DummyEventStore(EventStore):
    async def load_stream(self, aggregate_id) -> EventStream:
        events = db.get(aggregate_id)
        if not events:
            raise RuntimeError
        return EventStream(version=len(events), events=events)

    async def append_to_stream(
        self,
        aggregate_id,
        events: List[Event],
        expect_version: Optional[int] = None,
    ) -> None:
        if not db.get(aggregate_id):
            db[aggregate_id] = events
        else:
            if (
                expect_version is not None
                and len(db[aggregate_id]) is not expect_version
            ):
                raise ConcurrentStreamWriteError
            db[aggregate_id] = [*db[aggregate_id], *events]


async def close(_listen_task):
    await sleep(0.1)
    _listen_task.cancel()
    await _listen_task


async def reactor0(_):
    print("Hello reactor!")


async def twins():
    h1 = Human()
    await sleep(1)
    h1.execute(birth, "Otto")
    await human_repo.save(h1)


if __name__ == "__main__":
    loop = get_event_loop()

    human_bus = JsonEventBus(registry=HumanEvent.registry)
    human_bus.subscribe(reactor0, "human.born")
    # for stuff in config subscribe topic
    human_repo = HumanRepository(DummyEventStore(), event_bus=human_bus)
    listen_task = loop.create_task(human_bus.listen())

    loop.run_until_complete(twins())
    loop.run_until_complete(close(listen_task))
