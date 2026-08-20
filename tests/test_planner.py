from datetime import date, datetime
from zoneinfo import ZoneInfo

from flight_radar.config import load_config
from flight_radar.planner import effective_hours, leave_days


def test_friday_after_work_does_not_count_friday():
    config = load_config(__import__("pathlib").Path("config/radar.toml"))
    departure = datetime(2026, 9, 11, 21, 30)
    arrival = datetime(2026, 9, 14, 20, 0)
    assert leave_days(departure, arrival, "HGH", config) == 1


def test_pvg_transfer_can_make_evening_trip_leave_time():
    config = load_config(__import__("pathlib").Path("config/radar.toml"))
    departure = datetime(2026, 9, 11, 21, 30)
    arrival = datetime(2026, 9, 14, 20, 0)
    assert leave_days(departure, arrival, "PVG", config) == 2


def test_effective_hours_subtracts_destination_penalties():
    config = load_config(__import__("pathlib").Path("config/radar.toml"))
    out_arrival = datetime(2026, 9, 12, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    return_departure = datetime(2026, 9, 15, 20, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert abs(effective_hours(out_arrival, return_departure, "KIX", config) - 84.6667) < 0.01
