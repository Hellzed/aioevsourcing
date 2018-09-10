import asyncio
from asynctest import CoroutineMock

from abc import ABC
from dataclasses import dataclass

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


@pytest.fixture
def dummy_queue():
    queue = asyncio.Queue()
    queue.put = CoroutineMock()
    return queue


@pytest.fixture
def dummy_bus(dummy_queue):
    return events.JsonEventBus(
        registry=dummy_bus_event_registry, queue=dummy_queue
    )


@pytest.mark.asyncio
async def test_bus_publish(dummy_bus, dummy_queue):
    aggregate_id = "anonymous"
    await dummy_bus.publish(aggregate_id, DummyBusEvent())
    assert dummy_queue.put.assert_called
