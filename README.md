Event sourcing framework for asyncio.

TODO: Safer initialisation with robust initial event mechanism (to define ID and sane defaults. Obviously dataclass field defaults not backed by an event are not persisted).

# Getting Started

## Defining the domain

**_What is our data model?_**

The application domain is a collection of units of work called **aggregates**, each exposing relevant data as a set of fields.  

**_How do operate on that data?_**

An aggregate's current state is obtained by replaying the full chronology of **events** that ever affected it.  
An aggregate can and should only be mutated by appending new events after the latest one in the chronology.  
**Commands** are actions that mutate aggregates by issuing new events.

### Aggregates

An aggregate is the unit on which work is done, exposing data fields. It accepts compatible events.

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
    airport: str = "<unknown>"
```

### Events

Events represent an aggregate's state changes. They are responsible for applying their payload fields to an aggregate's state.

They should be defined as immutable.

**_Do not mutate events. Do not reuse instanciated events._**

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
    # A topic is necessary for event handling
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

Use commands to issue new events. A command always returns a single event at a time, unless it raises an error.

Commands may use the aggregate's state along arguments for synchronous operations (ie. validation, logging, dynamically change event types, raising errors...).

Commands example:
```python
# Plain functions are enough in most cases.
# Commands always take at least one argument: the aggregate.
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

Commands are run through the aggregate itself, with the `execute` method:
```python
aircraft = Aircraft()  # New ggregates are initialised like any other object
aircraft.execute(takeoff)
# Aircraft(airport='<unknown>', flying=True)
aircraft.execute(land, "Paris CDG")
# Aircraft(airport='Paris CDG', flying=False)
```
The `execute` method *is not asynchronous*. This an opinioned framework: commands are meant to be issued in a sequence, just like events are meant to be applied.  
None blocking calls would introduce an unwanted complexity in managing aggregate state transitions.

## Aggregate persistence

### The repository

Using a repository is a convenient way to save and load aggregates.

A repository needs an event store for streams of event affecting aggregates.

Defining and initialising a repository is simple:
```python
from aioevsourcing import aggregates, events

class AircraftRepository(aggregates.AggregateRepository):
    aggregate = Aircraft

# The simplest event store you can get: it relies on a dict to store data
event_store = events.DictEventStore()
aircrafts = AircraftRepository(event_store)
```
Saving and loading through the repository are non-blocking operations.

### Loading

Only an ID is needed to load an aggregate:
```python
aircraft = await aircrafts.load("DM2018")
```

### Saving

Saving is straightforward:
```python
await aircrafts.save(aircraft)
```

If you intend to load or create an aggregate, work on it, then save it, but normal application operation is interrupted somewhere in the middle, you may want to get warned about it. That's what transactions are for!

### Transactions

Transactions, context managers with the function `execute_transaction` will load or create an aggregate, and save it at the end.

If a transaction is interrupted (a typical case being an application forced shutdown during a long operation), a warning will be issued.

```python
# Create a new aggregate by only passing the repository as argument to the
# 'execute_transaction' call.
async with execute_transaction(aircrafts) as aircraft:
      aircraft.execute(takeoff)
# Our aircraft is in the air, and saved.

# Load an aggregate by passing repository as first argument and ID as second
# argument to the 'execute_transaction' call.
async with execute_transaction(aircrafts) as aircraft:
      aircraft.execute(land, "Amsterdam Schiphol")
# Our aircraft landed and is saved.
```

## A reactive application

### The event bus

### Reactors
