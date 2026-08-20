from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import RadarConfig

JAPAN_KOREA = {"NRT", "HND", "KIX", "FUK", "NGO", "CTS", "OKA", "ICN", "GMP", "CJU", "PUS"}


def airport_timezone(code: str) -> ZoneInfo:
    return ZoneInfo("Asia/Tokyo" if code.upper() in JAPAN_KOREA else "Asia/Shanghai")


def localize(value: datetime, airport: str) -> datetime:
    tz = airport_timezone(airport)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def date_windows(
    start: date,
    horizon_days: int,
    min_nights: int,
    max_nights: int,
) -> list[tuple[date, date, int]]:
    windows: list[tuple[date, date, int]] = []
    end = start + timedelta(days=horizon_days)
    for departure in (start + timedelta(days=offset) for offset in range(horizon_days + 1)):
        for nights in range(min_nights, max_nights + 1):
            return_date = departure + timedelta(days=nights)
            if return_date <= end + timedelta(days=max_nights):
                windows.append((departure, return_date, nights))
    return windows


def _is_workday(day: date, config: RadarConfig) -> bool:
    if day in config.forced_workdays:
        return True
    if day in config.holidays:
        return False
    return day.weekday() < 5


def leave_days(
    outbound_departure: datetime,
    return_arrival: datetime,
    origin: str,
    config: RadarConfig,
) -> int:
    origin_cfg = config.origin_for(origin)
    start = localize(outbound_departure, origin) - timedelta(
        minutes=origin_cfg.transfer_minutes + origin_cfg.airport_buffer_minutes
    )
    end = localize(return_arrival, origin) + timedelta(minutes=origin_cfg.transfer_minutes)
    tz = ZoneInfo(config.timezone)
    start = start.astimezone(tz)
    end = end.astimezone(tz)
    count = 0
    cursor = start.date()
    while cursor <= end.date():
        if _is_workday(cursor, config):
            work_start = datetime.combine(cursor, config.work_start, tzinfo=tz)
            work_end = datetime.combine(cursor, config.work_end, tzinfo=tz)
            if start < work_end and end > work_start:
                count += 1
        cursor += timedelta(days=1)
    return count


def effective_hours(
    outbound_arrival: datetime,
    return_departure: datetime,
    destination: str,
    config: RadarConfig,
) -> float:
    out = localize(outbound_arrival, destination)
    back = localize(return_departure, destination)
    elapsed = (back.astimezone(ZoneInfo("UTC")) - out.astimezone(ZoneInfo("UTC"))).total_seconds()
    elapsed -= config.penalty_for(destination) * 2 * 60
    return max(0.0, elapsed / 3600)
