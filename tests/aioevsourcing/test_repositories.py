# pylint: skip-file
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

    dummy_prop: str
    global_id: str = None


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
    return store


@pytest.fixture
def event_bus():
    bus = events.EventBus(registry=BaseDummyEvent.registry)
    return bus


@pytest.fixture
def repository(event_store, event_bus):
    return DummyRepository(event_store, bus=event_bus)


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
    event_bus.publish = CoroutineMock()
    event_store.append_to_stream = CoroutineMock()
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
async def test_repository_save_fail_global_id_is_none(
    repository, event_store, event_bus
):
    aggregate = DummyAggregate()
    with pytest.raises(ValueError):
        await repository.save(aggregate)


@pytest.mark.asyncio
async def test_repository_save_fail_uninitialised_fields(
    dummy_aggregate, repository
):
    repository = DummyRepository(event_store)
    aggregate = DummyAggregate()
    aggregate.execute(dummy_command_set_id, "some_aggregate_id_123")
    with pytest.raises(AttributeError):
        await repository.save(aggregate)


@pytest.mark.asyncio
async def test_repository_publish_fail_no_method_in_bus(
    repository, event_store
):
    repository_with_no_bus = DummyRepository(event_store, bus={})
    aggregate = DummyAggregate()
    aggregate.execute(dummy_command_set_id, "some_aggregate_id_123")
    aggregate.execute(dummy_command_a)
    with pytest.raises(AttributeError):
        await repository_with_no_bus.save(aggregate)


@pytest.mark.asyncio
async def test_repository_save_no_changes(repository, event_store, event_bus):
    aggregate = DummyAggregate()
    aggregate.execute(dummy_command_set_id, str(uuid.uuid4()))
    aggregate.mark_saved()
    with pytest.warns(SyntaxWarning):
        await repository.save(aggregate)


@pytest.mark.asyncio
async def test_repository_load(dummy_aggregate, repository, event_store):
    changes, aggregate_id = dummy_aggregate.changes, dummy_aggregate.global_id
    await repository.save(dummy_aggregate)
    event_store.load_stream = CoroutineMock(
        return_value=events.EventStream(version=len(changes), events=changes)
    )
    await repository.load(aggregate_id)
    event_store.load_stream.assert_called_once_with(aggregate_id)


@pytest.mark.asyncio
async def test_repository_load_fail_with_not_found(repository):
    with pytest.raises(aggregates.AggregateNotFoundError):
        await repository.load("555")


def test_repository_open_transaction(repository):
    aggregate_id = "<aggregate_id>"
    assert len(repository._active_transactions) is 0
    transaction_id = repository.open_transaction(aggregate_id)
    assert len(repository._active_transactions) is 1
    assert repository._active_transactions[transaction_id] is aggregate_id


def test_repository_close_transaction(repository):
    aggregate_id = "<aggregate_id>"
    transaction_id = repository.open_transaction(aggregate_id)
    assert len(repository._active_transactions) is 1
    repository.close_transaction(transaction_id)
    assert len(repository._active_transactions) is 0
    repository.close_transaction(transaction_id)
    assert len(repository._active_transactions) is 0


def test_repository_transaction_still_open_warning(repository, caplog):
    aggregate_id = "<aggregate_id>"
    transaction_id = repository.open_transaction(aggregate_id)
    repository.close()
    assert "active transactions on close" in caplog.text
    assert transaction_id in caplog.text


@pytest.mark.asyncio
async def test_execute_transaction_create_aggregate(repository):
    repository.load = CoroutineMock()
    repository.save = CoroutineMock()
    async with aggregates.execute_transaction(repository) as aggregate:
        repository.load.assert_not_called()
        assert isinstance(aggregate, repository.aggregate)
        assert len(repository._active_transactions) is 1
        aggregate_id = str(uuid.uuid4())
        aggregate.execute(dummy_command_set_id, aggregate_id)
        aggregate.execute(dummy_command_a)
    assert len(repository._active_transactions) is 0
    repository.save.assert_called_once_with(aggregate)


@pytest.mark.asyncio
async def test_execute_transaction_load_aggregate(dummy_aggregate, repository):
    await repository.save(dummy_aggregate)
    print(repository)
    repository.save = CoroutineMock()
    async with aggregates.execute_transaction(
        repository, dummy_aggregate.global_id
    ) as aggregate:
        assert len(repository._active_transactions) is 1
        aggregate.execute(dummy_command_b)
    assert len(repository._active_transactions) is 0
    repository.save.assert_called_with(aggregate)


@pytest.mark.asyncio
async def test_execute_transaction_not_a_repository():
    with pytest.raises(AttributeError):
        async with aggregates.execute_transaction(
            "not a repository"
        ) as aggregate:
            pass
