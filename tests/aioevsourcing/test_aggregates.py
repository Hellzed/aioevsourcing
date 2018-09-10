import pytest

from abc import ABC
from dataclasses import dataclass
from aioevsourcing import aggregates, commands, events


class DummyEvent(events.Event, ABC):
    pass


DUMMY_TYPES = (DummyEvent,)


@dataclass(init=False)
class DummyAggregate(aggregates.Aggregate):
    event_types = DUMMY_TYPES

    dummy_prop: str


@pytest.fixture
def aggregate():
    return DummyAggregate()


def test_aggregate_init(aggregate):
    assert aggregate.event_types is DUMMY_TYPES


def test_aggregate_init_empty(aggregate):
    assert aggregate.version is 0
    assert isinstance(aggregate.changes, list)
    assert len(aggregate.changes) is 0
    with pytest.raises(Exception) as excinfo:
        print(aggregate.dummy_prop)
    assert excinfo.type is AttributeError
    assert aggregate.saved is True


@dataclass(frozen=True)
class DummyPropChanged(DummyEvent):
    topic = "not.relevant.here"

    value: str

    def apply_to(self, _aggregate: DummyAggregate) -> None:
        _aggregate.dummy_prop = self.value


def test_aggregate_apply(aggregate):
    prop_value = "new value"
    aggregate.apply(DummyPropChanged(value=prop_value))
    assert aggregate.dummy_prop is prop_value


def test_aggregate_apply_many(aggregate):
    values = ["one", "two", "three"]
    for value in values:
        aggregate.apply(DummyPropChanged(value=value))
    assert aggregate.dummy_prop is values[-1]
    assert aggregate.saved is True


@dataclass(frozen=True)
class BadEvent(events.Event):
    topic = "still.not.relevant.here"

    value: str

    def apply_to(self, _aggregate: DummyAggregate) -> None:
        _aggregate.dummy_prop = self.value


def test_aggregate_apply_fail_with_bad_event(aggregate):
    prop_old_value = "old value"
    prop_new_value = "new value"
    aggregate.apply(DummyPropChanged(value=prop_old_value))
    with pytest.raises(aggregates.EventNotSupportedError):
        aggregate.apply(BadEvent(value=prop_new_value))
    assert aggregate.dummy_prop is prop_old_value


def test_aggregate_init_with_stream():
    last_event = DummyPropChanged(value="three")
    dummy_events = [
        DummyPropChanged(value="one"),
        DummyPropChanged(value="two"),
        last_event,
    ]
    aggregate_with_stream = DummyAggregate(
        events.EventStream(version=len(dummy_events), events=dummy_events)
    )
    assert aggregate_with_stream.version is len(dummy_events)
    assert isinstance(aggregate_with_stream.changes, list)
    assert len(aggregate_with_stream.changes) is 0
    assert aggregate_with_stream.dummy_prop is last_event.value
    assert aggregate_with_stream.saved is True


def test_aggregate_init_fail_with_bad_event_in_stream():
    dummy_events = [
        DummyPropChanged(value="one"),
        BadEvent(value="two"),
        DummyPropChanged(value="three"),
    ]
    event_stream = events.EventStream(
        version=len(dummy_events), events=dummy_events
    )
    with pytest.raises(aggregates.EventNotSupportedError):
        DummyAggregate(event_stream)


def test_aggregate_init_fail_with_bad_stream():
    with pytest.raises(aggregates.BadEventStreamError):
        DummyAggregate({})


def change_dummy_prop(_, value):
    return DummyPropChanged(value=value)


def test_aggregate_execute(aggregate):
    expected_value = "something"
    aggregate.execute(change_dummy_prop, expected_value)
    assert len(aggregate.changes) is 1
    assert aggregate.changes == [DummyPropChanged(value=expected_value)]
    assert aggregate.dummy_prop is expected_value
    assert aggregate.saved is False


def test_aggregate_execute_many(aggregate):
    values = ["one", "two", "three"]
    for value in values:
        aggregate.execute(change_dummy_prop, value)
    assert len(aggregate.changes) is len(values)
    assert aggregate.changes == [
        DummyPropChanged(value=value) for value in values
    ]
    assert aggregate.dummy_prop is values[-1]
    assert aggregate.saved is False


def bad_command_no_event(_):
    return None


def test_aggregate_fail_execute_no_event(aggregate):
    expected_value = "something"
    aggregate.apply(DummyPropChanged(value=expected_value))
    with pytest.raises(commands.MustReturnEventError):
        aggregate.execute(bad_command_no_event)
    assert len(aggregate.changes) is 0
    assert aggregate.dummy_prop is expected_value
    assert aggregate.saved is True


def bad_command_event_not_supported(_, value):
    return BadEvent(value=value)


def test_aggregate_fail_execute_event_not_supported(aggregate):
    expected_value = "something"
    aggregate.apply(DummyPropChanged(value=expected_value))
    with pytest.raises(aggregates.EventNotSupportedError):
        aggregate.execute(bad_command_event_not_supported, "bad stuff")
    assert len(aggregate.changes) is 0
    assert aggregate.dummy_prop is expected_value
    assert aggregate.saved is True


def test_aggregate_mark_saved(aggregate):
    expected_value = "something"
    aggregate.execute(change_dummy_prop, expected_value)
    aggregate.mark_saved()
    assert aggregate.dummy_prop is expected_value
    assert isinstance(aggregate.changes, list)
    assert len(aggregate.changes) is 0
    assert aggregate.version is 1
    assert aggregate.saved is True
