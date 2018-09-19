# pylint: skip-file
import pytest

from aioevsourcing import reactors


def test_reactor_decorator():
    registry = reactors.ReactorRegistry()

    @reactors.reactor(registry=registry, key="dummy")
    def dummy_reactor():
        pass

    assert registry == reactors.ReactorRegistry({"dummy": dummy_reactor})
