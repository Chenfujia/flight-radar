from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

from .domain import Evaluation, ItineraryQuote


SCHEMA = """
CREATE TABLE IF NOT EXISTS fare_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL,
    provider TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    departure_at TEXT NOT NULL,
    outbound_arrival_at TEXT NOT NULL,
    return_departure_at TEXT NOT NULL,
    return_arrival_at TEXT NOT NULL,
    airline TEXT NOT NULL,
    flight_numbers TEXT NOT NULL,
    price_per_person TEXT NOT NULL,
    fare_total TEXT NOT NULL,
    transfer_total TEXT NOT NULL,
    door_to_door_total TEXT NOT NULL,
    effective_price_per_person TEXT NOT NULL,
    currency TEXT NOT NULL,
    leave_days INTEGER NOT NULL,
    effective_hours REAL NOT NULL,
    deal_level TEXT,
    reasons TEXT NOT NULL,
    booking_url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fare_signature_time
    ON fare_history(signature, observed_at);
CREATE INDEX IF NOT EXISTS idx_fare_route_dates
    ON fare_history(origin, destination, departure_date, return_date, observed_at);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            "PRAGMA journal_mode=WAL;"
            "PRAGMA synchronous=NORMAL;"
            "PRAGMA foreign_keys=ON;"
            "PRAGMA busy_timeout=5000;"
        )
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def save_observation(
        self,
        quote: ItineraryQuote,
        evaluation: Evaluation,
    ) -> int:
        outbound = quote.outbound[0]
        inbound = quote.inbound[0]
        cursor = self.connection.execute(
            """
            INSERT INTO fare_history (
                signature, provider, origin, destination, departure_date, return_date,
                departure_at, outbound_arrival_at, return_departure_at, return_arrival_at,
                airline, flight_numbers, price_per_person, fare_total, transfer_total,
                door_to_door_total, effective_price_per_person, currency, leave_days,
                effective_hours, deal_level, reasons, booking_url, observed_at, notified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                quote.signature,
                quote.provider,
                outbound.origin,
                outbound.destination,
                quote.departure_date.isoformat(),
                quote.return_date.isoformat(),
                outbound.departure_at.isoformat(),
                outbound.arrival_at.isoformat(),
                inbound.departure_at.isoformat(),
                inbound.arrival_at.isoformat(),
                quote.airline,
                json.dumps(quote.flight_numbers, ensure_ascii=False),
                str(quote.price_per_person),
                str(quote.total_price),
                str(evaluation.transfer_total),
                str(evaluation.door_to_door_total),
                str(evaluation.effective_price_per_person),
                quote.currency,
                evaluation.leave_days,
                evaluation.effective_hours,
                evaluation.level.value if evaluation.level else None,
                json.dumps(evaluation.reasons, ensure_ascii=False),
                quote.booking_url,
                quote.observed_at.isoformat(),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def history_stats(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str,
    ) -> tuple[Decimal | None, int]:
        rows = self.connection.execute(
            """
            SELECT effective_price_per_person
            FROM fare_history
            WHERE origin = ? AND destination = ?
              AND departure_date = ? AND return_date = ?
              AND observed_at >= datetime('now', '-21 days')
            ORDER BY observed_at
            """,
            (origin, destination, departure_date, return_date),
        ).fetchall()
        values = [Decimal(row[0]) for row in rows]
        return (Decimal(str(median(values))) if values else None, len(values))

    def last_notification(self, signature: str) -> tuple[str | None, Decimal | None]:
        row = self.connection.execute(
            """
            SELECT deal_level, effective_price_per_person
            FROM fare_history
            WHERE signature = ? AND notified_at IS NOT NULL
            ORDER BY notified_at DESC LIMIT 1
            """,
            (signature,),
        ).fetchone()
        if row is None:
            return None, None
        return row["deal_level"], Decimal(row["effective_price_per_person"])

    def mark_notified(self, record_id: int) -> None:
        self.connection.execute(
            "UPDATE fare_history SET notified_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), record_id),
        )
        self.connection.commit()

    def recent_deals(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM fare_history
            WHERE deal_level IS NOT NULL
            ORDER BY observed_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def backup(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            self.connection.backup(target)
            target.commit()
        finally:
            target.close()

    def integrity_check(self) -> str:
        row = self.connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"
