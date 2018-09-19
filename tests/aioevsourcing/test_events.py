# pylint: skip-file
import pytest

from abc import ABC

from aioevsourcing import events


class BaseTestEvent(events.SelfRegisteringEvent, ABC):
    registry = events.EventRegistry()

    def apply_to(self, _):
        pass


def test_event_type_self_registering():
    class EventA(BaseTestEvent):
        topic = "a"

    class EventB(BaseTestEvent):
        topic = "b"

    assert BaseTestEvent.registry == events.EventRegistry(
        {EventA.topic: EventA, EventB.topic: EventB}
    )


def test_event_type_self_registering_fail_empty_topic():
    with pytest.raises(ValueError):

        class EventA(BaseTestEvent):
            topic = ""


def test_event_type_self_registering_fail_wrong_topic_type():
    with pytest.raises(TypeError):

        class EventA(BaseTestEvent):
            topic = 420


def test_passthrough_codec():
    class EventToEncode(events.Event):
        topic = "nothing"

        def apply_to(self, aggregate):
            pass

    msg = events.Message(aggregate_id="zero", event=EventToEncode())
    assert events.PassthroughCodec.encode(msg) is msg
    assert events.PassthroughCodec.decode(msg) is msg
