from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fli.models import (
    Airport,
    DateSearchFilters,
    FlightSearchFilters,
    FlightSegment as FliFlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    TripType,
)
from fli.search import SearchDates, SearchFlights

from .config import RadarConfig
from .domain import CalendarFare, FlightSegment, ItineraryQuote
from .planner import airport_timezone


def _airport(code: str) -> Airport:
    try:
        return Airport[code.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported airport code: {code}") from exc


def _airport_code(value: Any) -> str:
    return str(getattr(value, "name", getattr(value, "value", value))).lstrip("_").upper()


def _airline_code(value: Any) -> str:
    return str(getattr(value, "name", getattr(value, "value", value))).lstrip("_").upper()


def _aware_datetime(value: datetime, airport: str) -> datetime:
    tz = airport_timezone(airport)
    return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)


class FliAdapter:
    provider_name = "fli"

    def __init__(self, config: RadarConfig):
        self.config = config
        self.dates = SearchDates()
        self.flights = SearchFlights()

    def close(self) -> None:
        for client in (self.dates.client, self.flights.client):
            close = getattr(client, "close", None)
            if close:
                close()

    def _segments(
        self,
        origin: str,
        destination: str,
        departure: date,
        return_date: date,
    ) -> list[FliFlightSegment]:
        return [
            FliFlightSegment(
                departure_airport=[[_airport(origin), 0]],
                arrival_airport=[[_airport(destination), 0]],
                travel_date=departure.isoformat(),
            ),
            FliFlightSegment(
                departure_airport=[[_airport(destination), 0]],
                arrival_airport=[[_airport(origin), 0]],
                travel_date=return_date.isoformat(),
            ),
        ]

    def search_dates(
        self,
        origin: str,
        destination: str,
        start: date,
        end: date,
        nights: int,
    ) -> list[CalendarFare]:
        filters = DateSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=self.config.passengers),
            flight_segments=self._segments(
                origin, destination, start, start + timedelta(days=nights)
            ),
            stops=MaxStops.NON_STOP if self.config.nonstop_only else MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            from_date=start.isoformat(),
            to_date=end.isoformat(),
            duration=nights,
        )
        results = self.dates.search(
            filters,
            currency=self.config.currency,
            country="CN",
        ) or []
        observed_at = datetime.now(timezone.utc)
        fares: list[CalendarFare] = []
        for result in results:
            dates = result.date
            if len(dates) != 2:
                continue
            fares.append(
                CalendarFare(
                    provider=self.provider_name,
                    origin=origin,
                    destination=destination,
                    departure_date=dates[0].date(),
                    return_date=dates[1].date(),
                    price_per_person=Decimal(str(result.price)),
                    currency=result.currency or self.config.currency,
                    observed_at=observed_at,
                )
            )
        return fares

    def search_itineraries(
        self,
        origin: str,
        destination: str,
        departure: date,
        return_date: date,
    ) -> list[ItineraryQuote]:
        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=self.config.passengers),
            flight_segments=self._segments(origin, destination, departure, return_date),
            stops=MaxStops.NON_STOP if self.config.nonstop_only else MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
        )
        results = self.flights.search(
            filters,
            top_n=2,
            currency=self.config.currency,
            country="CN",
        ) or []
        quotes: list[ItineraryQuote] = []
        observed_at = datetime.now(timezone.utc)
        for result in results:
            if not isinstance(result, tuple) or len(result) != 2:
                continue
            outbound_result, inbound_result = result
            if outbound_result.price is None:
                continue
            outbound = tuple(self._convert_legs(outbound_result.legs))
            inbound = tuple(self._convert_legs(inbound_result.legs))
            if not outbound or not inbound:
                continue
            total = Decimal(str(outbound_result.price))
            quotes.append(
                ItineraryQuote(
                    provider=self.provider_name,
                    outbound=outbound,
                    inbound=inbound,
                    price_per_person=total / self.config.passengers,
                    total_price=total,
                    currency=outbound_result.currency or self.config.currency,
                    booking_url=self.flights.build_flight_booking_url(
                        (outbound_result, inbound_result),
                        currency=self.config.currency,
                        country="CN",
                    ),
                    observed_at=observed_at,
                )
            )
        return quotes

    def _convert_legs(self, legs: list[Any]) -> list[FlightSegment]:
        return [
            FlightSegment(
                origin=_airport_code(leg.departure_airport),
                destination=_airport_code(leg.arrival_airport),
                departure_at=_aware_datetime(
                    leg.departure_datetime,
                    _airport_code(leg.departure_airport),
                ),
                arrival_at=_aware_datetime(
                    leg.arrival_datetime,
                    _airport_code(leg.arrival_airport),
                ),
                carrier_code=_airline_code(leg.airline),
                flight_number=leg.flight_number,
            )
            for leg in legs
        ]
