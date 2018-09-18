import asyncio
from asynctest import MagicMock, CoroutineMock, create_autospec

from abc import ABC
from dataclasses import asdict, dataclass

import pytest


from aioevsourcing import aggregates, events


@dataclass
class DummyBusEvent(events.Event):
    topic = "dummy"

    def apply_to(self, _):
        pass


dummy_bus_event_registry = events.EventRegistry(
    {DummyBusEvent.topic: DummyBusEvent}
)


async def dummy_reactor(*_):
    pass


async def dummy_reactor_again(*_):
    pass


@pytest.fixture
def dummy_queue():
    queue = asyncio.Queue()
    queue.put = CoroutineMock()
    queue.get = CoroutineMock()
    return queue


@pytest.fixture
def dummy_bus(dummy_queue):
    bus = events.EventBus(registry=dummy_bus_event_registry, queue=dummy_queue)
    bus._event_listener = CoroutineMock()
    return bus


@pytest.mark.asyncio
async def test_bus_init(dummy_bus):
    with pytest.raises(StopAsyncIteration) as excinfo:
        await dummy_bus.__anext__()


@pytest.mark.asyncio
async def test_bus_subscribe(dummy_bus):
    dummy_bus.subscribe(dummy_reactor, "topic1")
    assert dummy_bus._subscriptions == {"topic1": {dummy_reactor}}

    dummy_bus.subscribe(dummy_reactor, "topic2")
    assert dummy_bus._subscriptions == {
        "topic1": {dummy_reactor},
        "topic2": {dummy_reactor},
    }

    dummy_bus.subscribe(dummy_reactor_again, "topic1", "topic2")
    assert dummy_bus._subscriptions == {
        "topic1": {dummy_reactor, dummy_reactor_again},
        "topic2": {dummy_reactor, dummy_reactor_again},
    }


@pytest.mark.asyncio
async def test_bus_publish(dummy_bus, dummy_queue):
    aggregate_id, dummy_event = "anonymous", DummyBusEvent()
    await dummy_bus.publish(aggregate_id, dummy_event)
    dummy_queue.put.assert_called_once_with(
        events.Message(aggregate_id="anonymous", event=DummyBusEvent())
    )


@pytest.mark.asyncio
async def test_bus_react(dummy_bus):
    mock_reactor = create_autospec(dummy_reactor)
    aggregate_id, dummy_event, context = "anonymous", DummyBusEvent(), {}
    dummy_bus.subscribe(mock_reactor, "dummy")
    await dummy_bus.react(
        events.Message(aggregate_id=aggregate_id, event=dummy_event)
    )
    mock_reactor.assert_called_once_with(aggregate_id, dummy_event, context)


@pytest.mark.asyncio
async def test_bus_listen(dummy_bus, dummy_queue):
    dummy_bus.listen()
    dummy_bus._event_listener.assert_called_once()
    assert isinstance(dummy_bus._listen_task, asyncio.Task)
