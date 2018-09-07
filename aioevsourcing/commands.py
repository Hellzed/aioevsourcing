"""aioevsourcing.commands

Provides base command and error classes for an event sourcing application.
"""
from abc import ABC, abstractmethod


class Command(ABC):
    """Command abstract base class. May be subclassed for command types.

    For simple commands, just use functions.
    """

    @abstractmethod
    def __call__(self, *args, **kwargs):
        pass


class CommandRuntimetError(RuntimeError):
    """Raise this error when a command's internal code fails.
    """

    pass


class MustReturnEventError(TypeError):
    """Raise this error when a command fails to return an event.
    """

    def __init__(self, command) -> None:
        super().__init__(
            "Command '{}.{}' did not return an Event. Commands must return a "
            "callable event that implements an 'apply_to' method.".format(
                command.__module__, command.__name__
            )
        )
