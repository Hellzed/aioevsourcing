from dataclasses import dataclass
from aioevsourcing.aggregates import Aggregate


@dataclass(init=False)
class DummyAggregate(Aggregate):
    command_types = ()
    event_types = ()


def test_hello():
    assert True
