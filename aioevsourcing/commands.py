"""aioevsourcing.commands

Provides base command and error classes for an event sourcing application.
"""
from typing import Callable, TypeVar

from aioevsourcing import events

CmdArgs = TypeVar("CmdArgs")
CmdKwargs = TypeVar("CmdKwargs")
Command = Callable[[object, CmdArgs, CmdKwargs], events.Event]


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
