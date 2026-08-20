from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class OriginConfig:
    code: str
    enabled: bool
    transfer_cost_total_cny: Decimal
    transfer_minutes: int
    airport_buffer_minutes: int


@dataclass(frozen=True)
class RadarConfig:
    path: Path
    project_root: Path
    timezone: str
    passengers: int
    work_start: time
    work_end: time
    max_leave_days: int
    search_horizon_days: int
    min_nights: int
    max_nights: int
    min_effective_hours: int
    currency: str
    nonstop_only: bool
    origins: tuple[OriginConfig, ...]
    destinations: tuple[str, ...]
    target_prices: dict[str, Decimal]
    airport_penalties: dict[str, int]
    scan_interval_minutes: int
    max_calendar_queries: int
    max_detail_queries: int
    jitter_ratio: float
    meaningful_drop_ratio: Decimal
    pushplus_endpoint: str
    pushplus_channel: str
    pushplus_token_env: str
    holidays: frozenset[date]
    forced_workdays: frozenset[date]

    @property
    def database_path(self) -> Path:
        return self.project_root / "data" / "radar.sqlite3"

    @property
    def backup_dir(self) -> Path:
        return self.project_root / "data" / "backups"

    @property
    def log_path(self) -> Path:
        return self.project_root / "logs" / "flight-radar.log"

    def target_for(self, destination: str) -> Decimal:
        return self.target_prices.get(destination, Decimal("999999"))

    def penalty_for(self, destination: str) -> int:
        return self.airport_penalties.get(
            destination, self.airport_penalties.get("default", 90)
        )

    def origin_for(self, code: str) -> OriginConfig:
        for origin in self.origins:
            if origin.code == code:
                return origin
        raise KeyError(f"Origin is not configured: {code}")


def _decimal(value: object, default: str = "0") -> Decimal:
    return Decimal(str(value if value is not None else default))


def _time(value: object, default: str) -> time:
    raw = str(value or default)
    return time.fromisoformat(raw)


def _dates(values: object) -> frozenset[date]:
    if not values:
        return frozenset()
    return frozenset(date.fromisoformat(str(value)) for value in values)


def load_config(path: Path) -> RadarConfig:
    path = path.expanduser().resolve()
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    profile = data.get("profile", {})
    work = data.get("work", {})
    trip = data.get("trip", {})
    flight = data.get("flight", {})
    scanner = data.get("scanner", {})
    alerts = data.get("alerts", {})
    pushplus = data.get("pushplus", {})

    origins: list[OriginConfig] = []
    for code, raw in data.get("origins", {}).items():
        origins.append(
            OriginConfig(
                code=str(code).upper(),
                enabled=bool(raw.get("enabled", True)),
                transfer_cost_total_cny=_decimal(raw.get("transfer_cost_total_cny")),
                transfer_minutes=int(raw.get("transfer_minutes", 0)),
                airport_buffer_minutes=int(raw.get("airport_buffer_minutes", 0)),
            )
        )

    if not origins:
        raise ValueError("At least one origin must be configured")
    destinations = tuple(str(item).upper() for item in data.get("destinations", {}).get("enabled", []))
    if not destinations:
        raise ValueError("At least one destination must be configured")

    return RadarConfig(
        path=path,
        project_root=path.parent.parent,
        timezone=str(profile.get("timezone", "Asia/Shanghai")),
        passengers=int(profile.get("passengers", 2)),
        work_start=_time(work.get("start"), "09:00"),
        work_end=_time(work.get("end"), "18:00"),
        max_leave_days=int(work.get("max_leave_days", 2)),
        search_horizon_days=int(trip.get("search_horizon_days", 45)),
        min_nights=int(trip.get("min_nights", 2)),
        max_nights=int(trip.get("max_nights", 4)),
        min_effective_hours=int(trip.get("min_effective_hours", 48)),
        currency=str(flight.get("currency", "CNY")).upper(),
        nonstop_only=bool(flight.get("nonstop_only", True)),
        origins=tuple(origin for origin in origins if origin.enabled),
        destinations=destinations,
        target_prices={
            str(code).upper(): _decimal(value)
            for code, value in data.get("target_price", {}).items()
        },
        airport_penalties={
            str(code).upper(): int(value)
            for code, value in data.get("airport_penalty_minutes", {}).items()
        },
        scan_interval_minutes=int(scanner.get("interval_minutes", 120)),
        max_calendar_queries=int(scanner.get("max_calendar_queries", 72)),
        max_detail_queries=int(scanner.get("max_detail_queries", 30)),
        jitter_ratio=float(scanner.get("jitter_ratio", 0.10)),
        meaningful_drop_ratio=_decimal(alerts.get("meaningful_drop_ratio"), "0.05"),
        pushplus_endpoint=str(
            pushplus.get("endpoint", "https://www.pushplus.plus/send")
        ),
        pushplus_channel=str(pushplus.get("channel", "app")),
        pushplus_token_env=str(pushplus.get("token_env", "PUSHPLUS_TOKEN")),
        holidays=_dates(data.get("calendar", {}).get("holidays")),
        forced_workdays=_dates(data.get("calendar", {}).get("forced_workdays")),
    )


def example_config() -> str:
    return """[profile]
timezone = "Asia/Shanghai"
passengers = 2

[work]
start = "09:00"
end = "18:00"
max_leave_days = 2

[trip]
search_horizon_days = 45
min_nights = 2
max_nights = 4
min_effective_hours = 48

[flight]
currency = "CNY"
nonstop_only = true

[origins.HGH]
enabled = true
transfer_cost_total_cny = 0
transfer_minutes = 60
airport_buffer_minutes = 120

[origins.PVG]
enabled = true
transfer_cost_total_cny = 260
transfer_minutes = 210
airport_buffer_minutes = 150

[destinations]
enabled = ["KIX", "NRT", "HND", "ICN", "GMP", "CJU", "PUS", "FUK", "NGO", "CTS", "OKA"]

[target_price]
KIX = 1650
NRT = 1850
HND = 1950
ICN = 1650
GMP = 1650
CJU = 1350
PUS = 1500
FUK = 1700
NGO = 1700
CTS = 2200
OKA = 1900

[airport_penalty_minutes]
HND = 45
NRT = 90
KIX = 70
ICN = 70
GMP = 35
CJU = 30
default = 90

[scanner]
interval_minutes = 120
max_calendar_queries = 72
max_detail_queries = 30
jitter_ratio = 0.10

[alerts]
meaningful_drop_ratio = 0.05

[pushplus]
endpoint = "https://www.pushplus.plus/send"
channel = "app"
token_env = "PUSHPLUS_TOKEN"

[calendar]
holidays = []
forced_workdays = []
"""
