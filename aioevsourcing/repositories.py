"""aioevsourcing.repositories

Provides a base repository class for an event sourcing application, to handle
saving/loading aggregates.
"""
import logging

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

# pylint: disable=wrong-import-order
# dataclasses is a standard module in Python 3.7
from dataclasses import dataclass, field
from typing import Any, Awaitable, List

from aioevsourcing import aggregates

LOGGER = logging.getLogger(__name__)


@dataclass
class EventStream:
    """An event stream is a versioned (ordered) list of events.

    It is used to save and replay, or otherwise transport events.

    Args:
        version (int): An version number. Defaults to 0.
        events (List[Event]): A list of Events. Default to an empty list.
    """

    version: int = 0
    events: List = field(default_factory=list)


class AggregateRepository(ABC):
    """AggregateRepository abstract base class.

    Subclass and add an `aggregate` class property to create your own
    repository.

    Args:
        event_bus (events.EventBus): Where events are published once stored.
        event_store (events.EventStore): Where events are stored.

    Attributes:
        aggregate (Type[Aggregate]): The type of the aggregates to save/load
            to/from this repository.
    """

    def __init__(self, event_store, event_bus=None) -> None:
        self.event_store = event_store
        self.event_bus = event_bus

    @property
    @abstractmethod
    def aggregate(self):
        """The aggregate type to load/save from this repository.
        """
        pass

    async def load(self, global_id: str) -> Awaitable[aggregates.Aggregate]:
        """Load an aggregate by ID.

        Args:
            global_id (str): The ID of the aggregate to load.

        Returns:
            Aggregate
        """
        # handle the AggregateNotFoundError case
        event_stream = await self.event_store.load_stream(global_id)
        return self.aggregate(event_stream)

    async def save(
        self, aggregate: aggregates.Aggregate, mark_saved: bool = True
    ) -> None:
        """Save an aggregate and publish changes to the event bus if present.

        Also marks the aggregate as saved by default.

        Args:
            aggregate (Aggregate): The ID of the aggregate to save.
        """
        await self.event_store.append_to_stream(
            aggregate.global_id,
            aggregate.changes,
            expect_version=aggregate.version,
        )
        if self.event_bus is not None:
            try:
                for event in aggregate.changes:
                    await self.event_bus.publish(aggregate.global_id, event)
            except AttributeError:
                LOGGER.error(
                    "Cannot 'publish' aggregate %s saved events to bus %r. "
                    "No such method!",
                    aggregate,
                    self.event_bus,
                )
        if mark_saved:
            aggregate.mark_saved()


@asynccontextmanager
async def execute_transaction(repository: Any, global_id: str = None):
    try:
        aggregate = None
        if global_id is not None:
            aggregate = await repository.load(global_id)
        else:
            aggregate = repository.aggregate()
        yield aggregate
        if aggregate is not None:
            await repository.save(aggregate)
    except AttributeError:
        LOGGER.error(
            "Repository '%r' must implement have an 'aggregate' attribute and "
            "define 'load' and 'save' methods. A repository type may be "
            "obtained by subclassing "
            "'aioeventsourcing.repositories.AggregateRepository'.",
            repository,
        )
        raise
