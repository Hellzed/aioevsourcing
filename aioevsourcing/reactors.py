"""aioevsourcing.commands

Provides base command and error classes for an event sourcing application.
"""
import inspect
import logging

from abc import ABC, abstractmethod
from typing import Dict, Type
from typing_extensions import Awaitable, Protocol

from aioevsourcing import events

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


class Reactor(Protocol):
    """Reactor protocol.

    Subclass to create your own reactor, or just provide an object compatible
    with the protocol.
    """

    key: str = None

    @abstractmethod
    async def __call__(
        self, aggregate_id: str, event: events.Event, context
    ) -> Awaitable:
        pass


class ReactorRegistry(Dict[str, Type[Reactor]]):
    """A reactor registry holding reactor types as values indexed by strings.

    Behaves as a normal dict, but useful for clarity and static type checking.
    """

    pass


class SelfRegisteringReactor(Reactor, ABC):
    """Self-registering reactor abstract base class.

    Subclass to create your own self-registering reactor.

    Attributes:
        registry (ReactorRegistry): A reactor registry. Defaults to an empty
            reactor registry.
    """

    registry: ReactorRegistry = ReactorRegistry()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            # pylint: disable=unsupported-assignment-operation
            if not cls.key:
                logger.warning("No key set for reactor %r", cls)
            elif not isinstance(cls.key, str):
                raise TypeError(
                    "{}: 'key' must be a 'str', not '{}'.".format(
                        cls, type(cls.key).__name__
                    )
                )
            else:
                cls.registry[cls.key] = cls


def reactor(registry: ReactorRegistry = None, key: str = None):
    """Decorate a function to and define a registry and a key to register it"""

    def reactor_decorator(func):
        if registry is not None and key is not None:
            registry[key] = func
        return func

    return reactor_decorator
