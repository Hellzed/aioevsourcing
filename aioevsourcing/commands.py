"""aioevsourcing.commands

Provides base command and error classes for an event sourcing application.
"""
from abc import abstractmethod
from typing import Any
from typing_extensions import Protocol

from aioevsourcing import events


class Command(Protocol):
    """Command protocol.

    Subclass to create your own command, or just provide an object compatible
    with the protocol.
    """

    __name__: str = "anonymous_command"

    @abstractmethod
    def __call__(
        self, aggregate: object, *args: Any, **kwargs: Any
    ) -> events.Event:
        pass


class CommandRuntimetError(RuntimeError):
    """Raise this error when a command's internal code fails.
    """

    pass


class MustReturnEventError(TypeError):
    """Raise this error when a command fails to return an event.
    """

    def __init__(self, command: Command) -> None:
        super().__init__(
            "Command '{}.{}' did not return an Event. Commands must return a "
            "callable event that implements an 'apply_to' method.".format(
                command.__module__, command.__name__
            )
        )
