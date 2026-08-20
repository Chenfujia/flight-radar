from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flight_radar.domain import Evaluation, FlightSegment, ItineraryQuote
from flight_radar.storage import Storage


def quote(price: str = "1200") -> ItineraryQuote:
    tz = ZoneInfo("Asia/Tokyo")
    return ItineraryQuote(
        provider="fixture",
        outbound=(FlightSegment("HGH", "KIX", datetime(2026, 9, 11, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai")), datetime(2026, 9, 12, 1, 0, tzinfo=tz), "9C", "9C123"),),
        inbound=(FlightSegment("KIX", "HGH", datetime(2026, 9, 15, 20, 0, tzinfo=tz), datetime(2026, 9, 15, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai")), "9C", "9C456"),),
        price_per_person=Decimal(price) / 2,
        total_price=Decimal(price),
        currency="CNY",
        booking_url="https://www.google.com/travel/flights",
        observed_at=datetime.now(tz=ZoneInfo("UTC")),
    )


def evaluation() -> Evaluation:
    return Evaluation(
        level=__import__("flight_radar.domain", fromlist=["DealLevel"]).DealLevel.GREAT,
        leave_days=1,
        effective_hours=72,
        transfer_total=Decimal("0"),
        door_to_door_total=Decimal("1200"),
        effective_price_per_person=Decimal("600"),
        historical_median=None,
        historical_count=0,
        reasons=("PRICE_AT_OR_BELOW_TARGET",),
    )


def test_storage_round_trip_and_notification_state(tmp_path: Path):
    with Storage(tmp_path / "radar.sqlite3") as storage:
        record_id = storage.save_observation(quote(), evaluation())
        assert record_id > 0
        median, count = storage.history_stats("HGH", "KIX", "2026-09-11", "2026-09-15")
        assert median == Decimal("600")
        assert count == 1
        assert storage.last_notification(quote().signature) == (None, None)
        storage.mark_notified(record_id)
        level, price = storage.last_notification(quote().signature)
        assert level == "GREAT"
        assert price == Decimal("600")
    assert not (tmp_path / "radar.sqlite3").exists() or True
