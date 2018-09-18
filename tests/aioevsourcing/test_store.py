from dataclasses import dataclass

import pytest

from aioevsourcing import events


@dataclass
class DummyStoreEvent(events.Event):
    topic = "dummy"

    dummy_prop: int

    def apply_to(self, _):
        pass


def test_dict_event_store_init():
    store = events.DictEventStore()
    assert isinstance(store._db, dict)
    assert store._db == {}


@pytest.mark.asyncio
async def test_dict_event_store_load_stream():
    KEY = "<aggregate_id>"
    db = {KEY: [DummyStoreEvent(1), DummyStoreEvent(2), DummyStoreEvent(3)]}
    store = events.DictEventStore(db)
    assert await store.load_stream(KEY) == events.EventStream(
        version=len(db[KEY]), events=db[KEY]
    )


@pytest.mark.asyncio
async def test_dict_event_store_append_to_stream():
    KEY = "<aggregate_id>"
    event_list = [DummyStoreEvent(1), DummyStoreEvent(2), DummyStoreEvent(3)]
    db = {}
    store = events.DictEventStore(db)
    await store.append_to_stream(
        global_id=KEY, events=event_list[:], expect_version=0
    )
    assert db == {KEY: event_list}

    new_event = DummyStoreEvent(4)
    await store.append_to_stream(
        global_id=KEY, events=[new_event], expect_version=len(db[KEY])
    )
    assert db == {KEY: [*event_list, new_event]}


@pytest.mark.asyncio
async def test_dict_event_store_append_to_stream_fail_with_concurrency():
    KEY = "<aggregate_id>"
    event_list = [DummyStoreEvent(1), DummyStoreEvent(2), DummyStoreEvent(3)]
    db = {}
    store = events.DictEventStore(db)
    await store.append_to_stream(
        global_id=KEY, events=event_list, expect_version=0
    )
    with pytest.raises(events.ConcurrentStreamWriteError):
        await store.append_to_stream(
            global_id=KEY, events=event_list, expect_version=0
        )
