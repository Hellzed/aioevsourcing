# pylint: skip-file
import asyncio
from asynctest import MagicMock, CoroutineMock, create_autospec

from abc import ABC
from dataclasses import asdict, dataclass

import logging

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
async def test_bus_iterate():
    queue = asyncio.Queue()
    bus = events.EventBus(registry=dummy_bus_event_registry, queue=queue)

    async def fake_task():
        pass

    bus._listen_task = asyncio.create_task(fake_task())
    await queue.put("item")
    assert await bus.__anext__() is "item"


@pytest.mark.asyncio
async def test_bus__react(dummy_bus):
    mock_reactor = create_autospec(dummy_reactor)
    aggregate_id, dummy_event, context = "anonymous", DummyBusEvent(), {}
    dummy_bus.subscribe(mock_reactor, "dummy")
    await dummy_bus._react(
        events.Message(aggregate_id=aggregate_id, event=dummy_event)
    )
    mock_reactor.assert_called_once_with(aggregate_id, dummy_event, context)


@pytest.mark.asyncio
async def test_bus__event_listener(caplog):
    queue = asyncio.Queue()
    bus = events.EventBus(registry=dummy_bus_event_registry, queue=queue)
    bus._react = CoroutineMock()

    async def fake_task():
        pass

    bus._listen_task = asyncio.create_task(fake_task())
    listen_task = asyncio.create_task(bus._event_listener())
    await asyncio.sleep(0)
    await queue.put("item")
    await asyncio.sleep(0)
    bus._react.assert_called_once_with("item")


@pytest.mark.asyncio
async def test_bus__event_listener_cancel_and_shield_react(
    caplog, monkeypatch
):
    caplog.set_level(logging.INFO)
    queue = asyncio.Queue()
    bus = events.EventBus(registry=dummy_bus_event_registry, queue=queue)

    async def fake_task():
        pass

    watch_value = "abcdef.123456"
    side_effect_duration = 0.1

    async def mockreact(message):
        await asyncio.sleep(side_effect_duration)
        logging.info(message)

    bus._react = mockreact
    bus._listen_task = asyncio.create_task(fake_task())
    listen_task = asyncio.create_task(bus._event_listener())
    await asyncio.sleep(0)

    # Trigger a side-effect by putting an item in the queue and waiting for the
    # listener to react
    await queue.put(watch_value)
    await asyncio.sleep(0)

    # Cancel the listening task
    listen_task.cancel()
    await listen_task

    # Side effect has not completed yet...
    assert watch_value not in caplog.text
    await asyncio.sleep(side_effect_duration * 2)

    # Side effect should complete and log the watched value now, because of the
    # cancellation shielding!
    assert watch_value in caplog.text


@pytest.mark.asyncio
async def test_bus_listen(dummy_bus, dummy_queue):
    dummy_bus.listen()
    dummy_bus._event_listener.assert_called_once()
    assert isinstance(dummy_bus._listen_task, asyncio.Task)


def test_bus_close(dummy_bus):
    loop = asyncio.get_event_loop()
    dummy_bus.listen()
    loop.run_until_complete(asyncio.sleep(0.1))
    dummy_bus.close(timeout=0.1)
