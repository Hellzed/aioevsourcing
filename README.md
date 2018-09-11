Event sourcing framework for asyncio.

# Getting Started

## Defining the domain

The application domain is a collection of units of work called aggregates, each exposing relevant data as a set of fields.

An aggregate's current state is obtained by replaying the full chronology of events that affected it in its lifetime.

An aggregate can and should only be mutated by appending new events after the latest one in the chronology.

Commands are actions that mutate aggregates by issuing new events.

### Aggregates

An aggregate is the unit on which work is done.

Aggregate definition example, using Python 3.7+ dataclass:
```python
from dataclasses import dataclass
from aioevsourcing import aggregates

# Create an aggregate
@dataclass(init=False)
class Aircraft(aggregates.Aggregate):
    # Register accepted event types
    event_types = (FlightEvent,)

    # Add fields
    flying: bool
    airport: str
```

### Events

Events represent an aggregate's state changes.

Event definition example, also using Python 3.7+ dataclass:
```python
from abc import ABC
from dataclasses import dataclass
from aioevsourcing import events

# Create a base event type as an Abstract Base Class
class FlightEvent(events.SelfRegisteringEvent, ABC):
  # Add fields
  flying: bool

  # Define an apply method shared by all events
  def apply_to(self, aircraft):
      aircraft.flying = self.flying

# Add some relevant events:
@dataclass(frozen=True)
class TakenOff(FlightEvent):
    topic = "aircraft.taken_off"

    # You may override shared fields inside an event
    flying: bool = True

@dataclass(frozen=True)
class Landed(FlightEvent):
    topic = "aircraft.landed"

    # New fields may be defined
    airport: str
    flying: bool = False

    # The apply method can also be overriden for an event
    def apply_to(self, aircraft):
        aircraft.flying = self.flying
        aircraft.airport = self.airport
```

### Commands

Use commands to issue new events. A command always returns a single event at a time.

*Do not mutate events. Do not reuse instanciated events.*

Commands example:
```python
# Plain functions are enough in most cases.
# Commands always take at least one argument: the aggregate
def takeoff(aircraft):
    return TakenOff()

def land(aircraft, airport):
    # Here you may:
    # - Log actions manually
    # - Check if the command applies given aggregate state
    # - Raise errors to handle in your business code
    # - Swap event types
    # For example:
    if not aircraft.flying:
        raise RuntimeError("Aircraft is already on the ground!")
    return Landed(airport=airport)
```
