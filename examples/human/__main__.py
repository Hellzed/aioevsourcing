import uuid
from abc import ABC
from asyncio import get_event_loop, sleep

# pylint: disable=wrong-import-order
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from aioevsourcing.aggregates import (
    Aggregate,
    AggregateRepository,
    execute_transaction,
)
from aioevsourcing.events import (
    ConcurrentStreamWriteError,
    Event,
    EventStore,
    EventStream,
    JsonEventBus,
    SelfRegisteringEvent,
)
from aioevsourcing.reactors import reactor, ReactorRegistry

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
        events = db.get(aggregate_id, [])
        # if not events:
        #     raise DataNotFoundError
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

    _listen_task.cancel()
    await _listen_task



reactors = ReactorRegistry()


@reactor(registry=reactors, key="say.hello")
async def reactor0(*_):
    print("enter r0")
    await sleep(1)
    print("Hello reactor!")


@reactor(registry=reactors, key="say.hello2")
async def reactor1(aggregate_id, *_):
    print("enter r1")
    async with execute_transaction(human_repo, aggregate_id) as h1:
        print("Retrieved name:", h1.name)


async def business():
    async with execute_transaction(human_repo) as h1:
        h1.execute(birth, "Otto")


if __name__ == "__main__":
    loop = get_event_loop()
    config = {"say.hello": ["human.born"], "say.hello2": ["human.born"]}

    human_bus = JsonEventBus(registry=HumanEvent.registry)
    for key in config:
        human_bus.subscribe(reactors[key], *config[key])

    human_repo = HumanRepository(DummyEventStore(), event_bus=human_bus)
    listen_task = loop.create_task(human_bus.listen())

    loop.run_until_complete(business())

    listen_task.cancel()
    loop.run_until_complete(sleep(3))
    loop.run_until_complete(listen_task)
