import pytest

from abc import ABC

from aioevsourcing import events


def test_event_type_self_registering():
    class BaseEvent(events.SelfRegisteringEvent, ABC):
        def apply_to(self, _):
            pass

    class EventA(BaseEvent):
        topic = "a"

    class EventB(BaseEvent):
        topic = "b"

    assert BaseEvent.registry == events.EventRegistry(
        {EventA.topic: EventA, EventB.topic: EventB}
    )
