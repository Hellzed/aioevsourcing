import asyncio

from abc import ABC
from dataclasses import dataclass
from typing import Optional

from aioevsourcing import aggregates, events


class FlightEvent(events.SelfRegisteringEvent, ABC):
    pass


@dataclass(init=False)
class Aircraft(aggregates.Aggregate):
    event_types = (FlightEvent,)

    flying: bool
    global_id: Optional[str] = None
    airport: Optional[str] = None


class AircraftRepository(aggregates.Repository):
    aggregate = Aircraft


@dataclass(frozen=True)
class Scheduled(FlightEvent):
    topic = "aircraft.scheduled"

    global_id: str

    def apply_to(self, aircraft):
        aircraft.global_id = self.global_id


@dataclass(frozen=True)
class TakenOff(FlightEvent):
    topic = "aircraft.taken_off"

    def apply_to(self, aircraft):
        aircraft.flying = True


@dataclass(frozen=True)
class Landed(FlightEvent):
    topic = "aircraft.landed"

    airport: str

    def apply_to(self, aircraft):
        aircraft.flying = False
        aircraft.airport = self.airport


def schedule(aircraft, _id):
    print("Scheduling flight with id", _id)
    return Scheduled(global_id=_id)


def takeoff(_):
    print("Taking off!")
    return TakenOff()


def land(aircraft, airport):
    if not aircraft.flying:
        raise RuntimeError("Aircraft is already on the ground!")
    print(aircraft.global_id, "landing in", airport)
    return Landed(airport=airport)


async def think_reactor(aggregate_id, event, context):
    await asyncio.sleep(1)
    print("Did we forget to pack something important?")


async def main(_aircrafts):
    async with aggregates.execute_transaction(aircrafts) as aircraft:
        aircraft.execute(schedule, "DAILY2018")
        aircraft.execute(takeoff)
    print("Aircraft status:", aircraft)
    await asyncio.sleep(2)
    async with aggregates.execute_transaction(
        aircrafts, "DAILY2018"
    ) as aircraft:
        aircraft.execute(land, "Paris CDG")
    print("Aircraft status:", aircraft)


if __name__ == "__main__":
    air_traffic_bus = events.EventBus(registry=FlightEvent.registry)
    air_traffic_bus.subscribe(think_reactor, TakenOff.topic)
    aircrafts = AircraftRepository(
        events.DictEventStore(), event_bus=air_traffic_bus
    )
    air_traffic_bus.listen()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(aircrafts))
    air_traffic_bus.close(timeout=5)
