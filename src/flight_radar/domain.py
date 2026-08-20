from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class DealLevel(StrEnum):
    GOOD = "GOOD"
    GREAT = "GREAT"
    EXCELLENT = "EXCELLENT"


@dataclass(frozen=True)
class FlightSegment:
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    carrier_code: str
    flight_number: str | None


@dataclass(frozen=True)
class CalendarFare:
    provider: str
    origin: str
    destination: str
    departure_date: date
    return_date: date
    price_per_person: Decimal
    currency: str
    observed_at: datetime


@dataclass(frozen=True)
class ItineraryQuote:
    provider: str
    outbound: tuple[FlightSegment, ...]
    inbound: tuple[FlightSegment, ...]
    price_per_person: Decimal
    total_price: Decimal
    currency: str
    booking_url: str
    observed_at: datetime

    @property
    def departure_date(self) -> date:
        return self.outbound[0].departure_at.date()

    @property
    def return_date(self) -> date:
        return self.inbound[0].departure_at.date()

    @property
    def stops_outbound(self) -> int:
        return max(0, len(self.outbound) - 1)

    @property
    def stops_inbound(self) -> int:
        return max(0, len(self.inbound) - 1)

    @property
    def airline(self) -> str:
        codes = {segment.carrier_code for segment in (*self.outbound, *self.inbound)}
        return ", ".join(sorted(codes))

    @property
    def flight_numbers(self) -> tuple[str, ...]:
        return tuple(
            segment.flight_number
            for segment in (*self.outbound, *self.inbound)
            if segment.flight_number
        )

    @property
    def signature(self) -> str:
        parts = [
            self.outbound[0].origin,
            self.outbound[-1].destination,
            *(
                f"{segment.carrier_code}{segment.flight_number or ''}:"
                f"{segment.departure_at.isoformat()}"
                for segment in (*self.outbound, *self.inbound)
            ),
        ]
        return "|".join(parts)


@dataclass(frozen=True)
class Evaluation:
    level: DealLevel | None
    leave_days: int
    effective_hours: float
    transfer_total: Decimal
    door_to_door_total: Decimal
    effective_price_per_person: Decimal
    historical_median: Decimal | None
    historical_count: int
    reasons: tuple[str, ...]

