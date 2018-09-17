import logging
import uuid
import os
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
    DictEventStore,
    EventStream,
    EventBus,
    SelfRegisteringEvent,
)
from aioevsourcing.reactors import reactor, ReactorRegistry

db: dict = {}
logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))


class Status(str, Enum):
    UNKNOWN = "unknown"
    ALIVE = "alive"
    DEAD = "dead"


class HumanEvent(SelfRegisteringEvent, ABC):
    pass


@dataclass(init=False)
class Human(Aggregate):
    event_types = (HumanEvent,)

    global_id: str = ""
    name: str = ""
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
    # do validation here
    print("Giving birth to a new human. His name will be {}!".format(name))
    return Born(name=name, global_id=str(uuid.uuid4()))


class HumanRepository(AggregateRepository):
    aggregate = Human


async def close(_listen_task):

    _listen_task.cancel()
    await _listen_task


reactors = ReactorRegistry()


@reactor(registry=reactors, key="say.hello")
async def reactor0(*_):
    print("enter r0")
    await sleep(3)
    print("Hello reactor!")


@reactor(registry=reactors, key="say.hello2")
async def reactor1(aggregate_id, *_):
    print("enter r1")
    # do aync stuff that does not require the aggregate here
    # h1 = await human_repo.load(aggregate_id)
    # do async stuff that requires the aggregate here
    async with execute_transaction(human_repo, aggregate_id) as h3:
        await sleep(12)
        print("Retrieved name:", h3.name)


async def business():
    async with execute_transaction(human_repo) as h1:
        h1.execute(birth, "Otto")

    async with execute_transaction(human_repo) as h2:
        pass


if __name__ == "__main__":
    loop = get_event_loop()
    config = {"say.hello": ["human.born"], "say.hello2": ["human.born"]}

    human_bus = EventBus(registry=HumanEvent.registry)
    for key in config:
        try:
            human_bus.subscribe(reactors[key], *config[key])
        except KeyError:
            logger.warning("No reactor found for config key '%s'!", key)

    human_repo = HumanRepository(DictEventStore(), event_bus=human_bus)
    human_bus.listen()

    loop.run_until_complete(business())

    #
    loop.run_until_complete(sleep(2))

    human_bus.close(timeout=2)
    human_repo.close()
    # loop.run_until_complete(listen_task)
