Event sourcing framework for [asyncio](https://docs.python.org/3/library/asyncio.html).

- [ ] Document how to extend the framework (asyncio.Queue compatible queue, message encoder, subclass event store for different backends)
- [ ] Redis example event store and event bus
- [ ] First evnt initialisation mechanism if needed
- [ ] Maybe freeze the bus conf once it starts listening


# Table of contents

- [Getting Started](#getting-started)
  - [Defining the Domain](#defining-the-domain)
    - [Aggregates](#aggregates)
    - [Events](#events)
    - [Commands](#commands)
  - [Aggregate Persistence](#aggregate-persistence)
    - [The Repository](#the-repository)
    - [Loading](#loading)
    - [Saving](#saving)
    - [Transactions](#transactions)
  - [A Reactive Application](#a-reactive-application)
    - [The event bus](#the-event-bus)
    - [Reactors](#reactors)
    - [Event Bus Lifecycle](#event-bus-lifecycle)


# Getting Started

## Defining the domain

**_What is our data model?_**

The application domain is a collection of units of work called **aggregates**, each exposing relevant data as a set of fields.  

**_How do we operate on that data? (create/read/update operations)_**

An aggregate's current state is obtained by initialising an empty aggregate of the appropriate type and immediately replaying the full list of **events** that ever affected the read aggregate, all in chronological order.  
An aggregate must only ever be mutated by appending new events after the latest one in the chronology.  
A **command** is an action that issues a new event applied to mutate an aggregate.

### Aggregates

An aggregate is the unit on which work is done, exposing data fields. It accepts compatible events. _Obvious aggregates are "User", "Ticket", "Aircraft"..._

_Aggregate definition example, using Python 3.7+ dataclass:_
```python
from dataclasses import dataclass
from aioevsourcing import aggregates

# Create an aggregate
@dataclass(init=False)
class Aircraft(aggregates.Aggregate):
    # Register accepted event types
    event_types = (TakenOff, Landed)

    # Add fields
    flying: bool
    airport: str = "<unknown>"
```
>**Note:** Python 3.7+ dataclasses are not mandatory to define aggregates or events. However, exposing fields and some other features is expected from data storage classes, and dataclasses conveniently do the heavy lifting for us.  
Read more about [dataclasses on the Python documentation](https://docs.python.org/3/library/dataclasses.html).

>**Note:** `@dataclass(init=False)` is used for aggregates because a dataclass-generated init method is not useful or wanted here: an aggregate is initialised by replaying events, not setting fields directly.

### Events

Events represent an aggregate's state changes. They are responsible for applying their own payload fields to an aggregate's state.

**_Do not mutate events. Do not reuse instanciated events._**

_Event definition example, also using Python 3.7+ dataclass:_
```python
from dataclasses import dataclass
from aioevsourcing import events

# Add some relevant events:
@dataclass(frozen=True)
class TakenOff(FlightEvent):
    # A topic is necessary for event handling
    topic = "aircraft.taken_off"

    # Define fields inside an event, with defaults, for example
    flying: bool = True

    def apply_to(self, aircraft):
        aircraft.flying = self.flying
```
>**Note:** `@dataclass(frozen=True)` is used on events because it helps enforcing the immutability rule. This discourages creating an event, applying it somewhere then mutating and ending up with inconsistent aggregate state.  

### Commands

Use commands to issue new events. A command always returns a single event at a time, unless it raises an error.

Commands may use the aggregate's state along arguments for synchronous operations (ie. validation, logging, dynamically change event types, raising errors...).

_Commands example:_
```python
# Plain functions are enough in most cases.
# Commands always take at least one argument: the aggregate.
def takeoff(aircraft):
    # Here you may:
    # - Log actions manually
    # - Check if the command applies given aggregate state
    # - Raise errors to handle in your business code
    # - Swap event types
    return TakenOff()
```

Commands are run through the aggregate itself, with the `execute` method:
```python
aircraft = Aircraft()  # New aggregates are initialised like any other object
aircraft.execute(takeoff)
# Aircraft(airport='<unknown>', flying=True)
aircraft.execute(land, "Paris CDG")
# Aircraft(airport='Paris CDG', flying=False)
```
The `execute` method *is not asynchronous*. This is an opinionated framework: commands are meant to be issued in a sequence, just like events are meant to be applied.  
Non-blocking calls would introduce an unwanted complexity in managing aggregate state transitions.

An aggregate mutated with the `execute` method (on command success) now contains _changes_, events that happened since it was loaded.
```python
aircraft.changes
# [TakenOff(flying=True), Landed(flying=False, airport="Paris CDG")]
aircraft.saved
# False
```
**_How do we persist these changes?_**

## Aggregate persistence

Because of our data model, aggregates exist as **streams** (versioned lists) of events in our storage, the **event store**.

**_How do we load or save an aggregate without querrying the event store, or handling event streams ourselves?_**

### The repository

Using a **repository** is a convenient way to save and load aggregates.

A repository needs an event store for streams of event affecting aggregates.

_Defining and initialising a repository is simple:_
```python
from aioevsourcing import aggregates, events

class AircraftRepository(aggregates.Repository):
    aggregate = Aircraft

# The simplest event store you can get: it relies on a dict to store data
event_store = events.DictEventStore()
aircrafts = AircraftRepository(event_store)
```
Saving and loading through the repository are non-blocking operations.

### Loading

Only an ID is needed to load an aggregate. _Example:_
```python
aircraft = await aircrafts.load("DM2018")
```

### Saving

Saving is straightforward. _Example:_
```python
await aircrafts.save(aircraft)
```

If you intend to load or create an aggregate, work on it, then save it, but normal application operation is interrupted somewhere in the middle, you may want to get warned about it. That's what transactions are for!

### Transactions

Transactions, context managers with the function `execute_transaction(repository [, aggregate ID])` will load or create an aggregate, and save it at the end.

If a transaction is interrupted (a typical case being an application forced shutdown during a long operation), a warning will be issued.

_Thanks to Python 3.7+, these are async context mangers:_
```python
# Create a new aggregate by only passing the repository as argument to the
# 'execute_transaction' call.
async with aggregates.execute_transaction(aircrafts) as aircraft:
      aircraft.execute(takeoff)
# Our aircraft is in the air, and saved.

# Load an aggregate by passing repository as first argument and ID as second
# argument to the 'execute_transaction' call.
async with aggregates.execute_transaction(aircrafts) as aircraft:
      aircraft.execute(land, "Amsterdam Schiphol")
# Our aircraft landed and is saved.
```
>**Note:** To get the full benefit of repository-managed transactions, there should be a single repository object per agregate type and the repository objects should ideally have the same lifetime as your application. Pass them around as a resources.  
Singleton is not enforced at framework-level for repositories.

## A reactive application

A complete application needs the ability to react to things that have happened in the domain (a.k.a. events).

An aggregate repository, if provided with an **event bus** (called "broker" elsewhere), will publish changes over this bus on save, always in the form of a stream of events.  
At the same time, the event bus will dispatch events in real time to **reactors** subscribing to the events' topics.

Reactors can then run any kind of asynchronous code, including new transactions.

### The event bus

_Back to the repository initialisation, in the following example an event bus is added:_
```python
# A simple bus, notice the base event we use provides the registry of known events
air_traffic_bus = events.EventBus(registry=FlightEvent.registry)
aircrafts = AircraftRepository(
    events.DictEventStore(),
    event_bus=air_traffic_bus
)
```
>**Note:** Any compatible event registry can be used.

At this point, events are published to the bus, but not listened to.

### Reactors

Reactors are plain coroutines. The event bus provides a `subscribe` method to register them to the bus under a specific topic.

A reactor can only subscribe once to a topic.

When triggered, the reactor is provided with three arguments, in the following order: the ID of the aggregate for which an event was published, the triggering event, a context value.

_Example of a reactor definition and subscription:_
```python
async def think_reactor(aggregate_id, event, context):
    ...
    await asyncio.sleep(1) # Sync and async operations
    print("Did we forget to pack something important?")

# Subscribe the reactor to a topic
air_traffic_bus.subscribe(think_reactor, "aircraft.taken_off")
```

### Event bus lifecycle

The event bus' lifecycle must be respected:
1. Create the event bus
2. Subscribe reactors to topics (with `subscribe(reactor, topic)`)
3. Start listening (with `listen()`)
4. Close the bus (with the coroutine method `close()`)

_Example of event bus lifecycle:_
```python
# Getting the bus ready
air_traffic_bus = events.EventBus(
    registry=FlightEvent.registry,
    encoder=MessageEncoder
)
air_traffic_bus.subscribe(think_reactor, "aircraft.taken_off")
air_traffic_bus.listen()

# Then, before exiting the application
await air_traffic_bus.close()
```
>**Note:** To be on the safe side, as long as the event bus is registered to a repository, events may be published in it, *even if it is "closed"*.  
A "closed" bus will only stop dispatching queued events to reactors.  
This method is called `close` for two reasons:  
>- compatibility with the shutdown convention of registered clients in asyncio/aiohttp applications;
>- it has a cusomisable timeout, during which it offers some relative guarantee that current running reactors are shielded from task cancellation by asyncio, making it suitable for a clean shutdown of the application.

Here is the full code of the [flights example](examples/flight/__main__.py).
