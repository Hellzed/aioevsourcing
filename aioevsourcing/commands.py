import logging

from abc import ABC, abstractmethod

from .events import Event


class Command(ABC):
    valid: bool = True

    def __post_init__(self):
        try:
            self.validate_args()
        except InvalidArgumentsError:
            logging.error("Invalid command: argument error")
            object.__setattr__(self, "valid", False)
        except NotImplementedError:
            pass

    async def __call__(self, aggregate) -> None:
        if not self.valid:
            return

        with aggregate:
            try:
                self._before_run(aggregate)
            except InvalidStateError:
                logging.error(
                    "Aggregate state doesn't allow running this command"
                )
                return
            except NotImplementedError:
                pass

            try:
                event = await self._run(aggregate)
                if not isinstance(event, Event):
                    raise MustReturnEventError
                aggregate.apply(event)
                aggregate.changes.append(event)
            except CommandRuntimeError:
                logging.error("%r: Failed to run on %r.", self, aggregate)

    def _before_run(self, aggregate):
        raise NotImplementedError

    def validate_args(self):
        raise NotImplementedError

    @abstractmethod
    async def _run(self, aggregate) -> Event:
        pass


class CommandRuntimeError(RuntimeError):
    pass


class ConcurrentCommandsError(RuntimeError):
    """Raise if attempting to run multiple "safe" commands at the same time.
    """

    def __init__(self, command) -> None:
        super().__init__(
            "Command '{}.{}' did not return an Event. "
            "Commands must return Events.".format(
                command.__module__, command.__name__
            )
        )


class InvalidArgumentsError(RuntimeError):
    pass


class InvalidStateError(RuntimeError):
    pass


class MustReturnEventError(TypeError):
    """Raise this error when a command fails to return an Event.
    """

    def __init__(self, command) -> None:
        super().__init__(
            "Command '{}.{}' did not return an Event. "
            "Commands must return Events.".format(
                command.__module__, command.__name__
            )
        )
