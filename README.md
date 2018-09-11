Event sourcing framework for asyncio

# Getting Started

The application domain is described through aggregates and events.
Commands are actions that mutate the domain.

An aggregate represents a unit of work as a set of fields, and is only mutated by applying compatible events.
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

Events represent mutations of an aggregate.
```python
from dataclasses import dataclass
from aioevsourcing import events

# Create a base event type
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

Use commands to issue new events. A command always returns a single event at a time.
*Do not reuse instanciated events.*
```python
# Plain functions are enough in most cases.
# A command always return
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
