import uuid
from abc import ABC
from asyncio import get_event_loop, sleep

# pylint: disable=wrong-import-order
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from aioevsourcing.aggregates import Aggregate
from aioevsourcing.repositories import (
    AggregateRepository,
    EventStream,
    execute_transaction,
)
from aioevsourcing.events import (
    Event,
    JsonEventBus,
    EventStore,
    ConcurrentStreamWriteError,
    SelfRegisteringEvent,
)

db: dict = {}


class Status(str, Enum):
    UNKNOWN = "unknown"
    ALIVE = "alive"
    DEAD = "dead"


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
    global_id: str
    status: Status = Status.ALIVE

    def apply_to(self, human: Human) -> None:
        human.name = self.name
        human.global_id = self.global_id
        human.status = self.status


def birth(_, name) -> Event:
    print("Giving birth to a new human. His name will be {}!".format(name))
    return Born(name=name, global_id=str(uuid.uuid4()))


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


async def business():
    human_one_id = None

    async with execute_transaction(human_repo) as h1:
        await sleep(1)
        h1.execute(birth, "Otto")
        human_one_id = h1.global_id

    async with execute_transaction(human_repo, human_one_id) as h1_again:
        await sleep(1)
        print("Retrieved name:", h1_again.name)

if __name__ == "__main__":
    loop = get_event_loop()

    human_bus = JsonEventBus(registry=HumanEvent.registry)
    human_bus.subscribe(reactor0, "human.born")
    # for stuff in config subscribe topic
    human_repo = HumanRepository(DummyEventStore(), event_bus=human_bus)
    listen_task = loop.create_task(human_bus.listen())

    loop.run_until_complete(business())
    loop.run_until_complete(close(listen_task))
