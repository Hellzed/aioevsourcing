import sys
import uuid
import warnings

from abc import ABC
from dataclasses import dataclass, field

import pytest

from asynctest import CoroutineMock

from aioevsourcing import aggregates, events

if not sys.warnoptions:
    warnings.simplefilter("ignore", ResourceWarning)


class BaseDummyEvent(events.SelfRegisteringEvent, ABC):
    registry = events.EventRegistry()

    dummy_prop: str

    def apply_to(self, aggregate):
        aggregate.dummy_prop = self.dummy_prop


@dataclass(frozen=True)
class DummyIdSet(BaseDummyEvent):
    topic = "dummy.id_set"

    global_id: str

    def apply_to(self, aggregate):
        aggregate.global_id = self.global_id


@dataclass(frozen=True)
class DummyEventA(BaseDummyEvent):
    topic = "dummy.a"

    dummy_prop: str = "The letter A"


@dataclass(frozen=True)
class DummyEventB(BaseDummyEvent):
    topic = "dummy.b"

    dummy_prop: str = "The letter B"


@dataclass(init=False)
class DummyAggregate(aggregates.Aggregate):
    event_types = (BaseDummyEvent,)

    global_id: str
    dummy_prop: str


class DummyRepository(aggregates.Repository):
    aggregate = DummyAggregate


def dummy_command_set_id(_, global_id):
    return DummyIdSet(global_id=global_id)


def dummy_command_a(_):
    return DummyEventA()


def dummy_command_b(_):
    return DummyEventB()


@pytest.fixture
def event_store():
    store = events.DictEventStore()
    store.append_to_stream = CoroutineMock()
    store.load_stream = CoroutineMock()
    return store


@pytest.fixture
def event_bus():
    bus = events.EventBus(registry=BaseDummyEvent.registry)
    bus.publish = CoroutineMock()
    return bus


@pytest.fixture
def repository(event_store, event_bus):
    return DummyRepository(event_store, event_bus=event_bus)


@pytest.fixture
def dummy_aggregate():
    aggregate = DummyAggregate()
    aggregate_id = str(uuid.uuid4())
    aggregate.execute(dummy_command_set_id, aggregate_id)
    return aggregate


def test_repository_init(repository):
    assert repository.aggregate is DummyAggregate


@pytest.mark.asyncio
async def test_repository_save(
    dummy_aggregate, repository, event_store, event_bus
):

    await repository.save(dummy_aggregate)
    event_store.append_to_stream.assert_called_once_with(
        dummy_aggregate.global_id,
        [DummyIdSet(global_id=dummy_aggregate.global_id)],
        expect_version=0,
    )
    event_bus.publish.assert_called_once_with(
        dummy_aggregate.global_id,
        DummyIdSet(global_id=dummy_aggregate.global_id),
    )
    assert dummy_aggregate.saved is True


@pytest.mark.asyncio
async def test_repository_load(dummy_aggregate, repository, event_store):
    aggregate_id = dummy_aggregate.global_id
    await repository.save(dummy_aggregate)
    await repository.load(aggregate_id)
    event_store.load_stream.assert_called_once_with(aggregate_id)
