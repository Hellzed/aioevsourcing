"""aioevsourcing.commands

Provides base command and error classes for an event sourcing application.
"""
import logging

from typing import Callable, Dict, Optional

from aioevsourcing import events

logger = logging.getLogger(__name__)  # pylint: disable=invalid-name

Reactor = Callable[[str, events.Event, Dict], None]


class ReactorRegistry(Dict[str, Reactor]):
    """A reactor registry holding reactor types as values indexed by strings.

    Behaves as a normal dict, but useful for clarity and static type checking.
    """

    pass


def reactor(
    registry: Optional[ReactorRegistry] = None, key: Optional[str] = None
) -> Callable[[Reactor], Reactor]:
    """Decorate a function to and define a registry and a key to register it"""

    def reactor_decorator(func: Reactor) -> Reactor:
        if registry is not None and key is not None:
            registry[key] = func
        return func

    return reactor_decorator
