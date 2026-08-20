from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import RadarConfig
from .deals import classify, should_notify
from .domain import DealLevel, Evaluation, ItineraryQuote
from .fli_adapter import FliAdapter
from .planner import effective_hours, leave_days
from .storage import Storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanSummary:
    calendar_queries: int
    detail_queries: int
    quotes_saved: int
    alerts_sent: int
    errors: int


def _level(value: str | None) -> DealLevel | None:
    if not value:
        return None
    try:
        return DealLevel(value)
    except ValueError:
        return None


def _money(value: Decimal) -> str:
    return f"¥{value.quantize(Decimal('0.01')):,.2f}"


def _content(quote: ItineraryQuote, evaluation: Evaluation) -> str:
    outbound = quote.outbound[0]
    inbound = quote.inbound[0]
    level = evaluation.level.value if evaluation.level else "普通价格"
    reasons = "、".join(evaluation.reasons) or "满足个人行程规则"
    return "\n".join(
        [
            f"{outbound.origin} → {outbound.destination} {level}",
            f"{outbound.departure_at:%Y-%m-%d %H:%M} → {outbound.arrival_at:%m-%d %H:%M}",
            f"{inbound.departure_at:%Y-%m-%d %H:%M} → {inbound.arrival_at:%m-%d %H:%M}",
            f"航司：{quote.airline}，直飞",
            f"价格：{_money(quote.price_per_person)} / 人",
            f"机票总价：{_money(quote.total_price)}",
            f"接驳成本：{_money(evaluation.transfer_total)}",
            f"门到门总成本：{_money(evaluation.door_to_door_total)}",
            f"请假：{evaluation.leave_days} 天",
            f"有效旅行：{evaluation.effective_hours:.1f} 小时",
            f"原因：{reasons}",
            f"查询时间：{quote.observed_at.astimezone(ZoneInfo('Asia/Shanghai')):%Y-%m-%d %H:%M}",
            "价格是搜索快照，请打开页面确认。",
        ]
    )


class Scanner:
    def __init__(
        self,
        config: RadarConfig,
        adapter: FliAdapter,
        storage: Storage,
        notifier: object,
    ):
        self.config = config
        self.adapter = adapter
        self.storage = storage
        self.notifier = notifier

    def run(self, today: date | None = None) -> ScanSummary:
        start = today or datetime.now(ZoneInfo(self.config.timezone)).date()
        end = start.fromordinal(start.toordinal() + self.config.search_horizon_days)
        calendar_queries = detail_queries = quotes_saved = alerts_sent = errors = 0
        candidates: dict[tuple[str, str, date, date], object] = {}

        for origin in self.config.origins:
            for destination in self.config.destinations:
                for nights in range(self.config.min_nights, self.config.max_nights + 1):
                    if calendar_queries >= self.config.max_calendar_queries:
                        break
                    try:
                        fares = self.adapter.search_dates(
                            origin.code, destination, start, end, nights
                        )
                        calendar_queries += 1
                    except Exception:
                        errors += 1
                        logger.exception(
                            "calendar query failed origin=%s destination=%s nights=%s",
                            origin.code,
                            destination,
                            nights,
                        )
                        continue
                    target = self.config.target_for(destination)
                    selected = sorted(
                        (
                            fare
                            for fare in fares
                            if fare.price_per_person <= target * Decimal("1.10")
                        ),
                        key=lambda fare: fare.price_per_person,
                    )[:2]
                    for fare in selected:
                        candidates[
                            (
                                fare.origin,
                                fare.destination,
                                fare.departure_date,
                                fare.return_date,
                            )
                        ] = fare

        for origin, destination, departure, return_date in list(candidates)[: self.config.max_detail_queries]:
            try:
                quotes = self.adapter.search_itineraries(
                    origin, destination, departure, return_date
                )
                detail_queries += 1
            except Exception:
                errors += 1
                logger.exception(
                    "detail query failed origin=%s destination=%s date=%s/%s",
                    origin,
                    destination,
                    departure,
                    return_date,
                )
                continue
            for quote in quotes:
                evaluation = self._evaluate(quote)
                if evaluation is None:
                    continue
                record_id = self.storage.save_observation(quote, evaluation)
                quotes_saved += 1
                if evaluation.level and self._send_if_needed(quote, evaluation):
                    self.storage.mark_notified(record_id)
                    alerts_sent += 1

        return ScanSummary(
            calendar_queries=calendar_queries,
            detail_queries=detail_queries,
            quotes_saved=quotes_saved,
            alerts_sent=alerts_sent,
            errors=errors,
        )

    def _evaluate(self, quote: ItineraryQuote) -> Evaluation | None:
        if self.config.nonstop_only and (
            quote.stops_outbound > 0 or quote.stops_inbound > 0
        ):
            return None
        origin = quote.outbound[0].origin
        destination = quote.outbound[-1].destination
        leave = leave_days(
            quote.outbound[0].departure_at,
            quote.inbound[-1].arrival_at,
            origin,
            self.config,
        )
        hours = effective_hours(
            quote.outbound[-1].arrival_at,
            quote.inbound[0].departure_at,
            destination,
            self.config,
        )
        if leave > self.config.max_leave_days or hours < self.config.min_effective_hours:
            return None
        transfer = self.config.origin_for(origin).transfer_cost_total_cny
        door_total = quote.total_price + transfer
        effective_pp = door_total / self.config.passengers
        median, count = self.storage.history_stats(
            origin,
            destination,
            quote.departure_date.isoformat(),
            quote.return_date.isoformat(),
        )
        level, reasons = classify(
            effective_pp,
            self.config.target_for(destination),
            median,
            count,
            hours,
        )
        return Evaluation(
            level=level,
            leave_days=leave,
            effective_hours=hours,
            transfer_total=transfer,
            door_to_door_total=door_total,
            effective_price_per_person=effective_pp,
            historical_median=median,
            historical_count=count,
            reasons=reasons,
        )

    def _send_if_needed(self, quote: ItineraryQuote, evaluation: Evaluation) -> bool:
        previous_raw, previous_price = self.storage.last_notification(quote.signature)
        previous = _level(previous_raw)
        if not should_notify(
            previous,
            previous_price,
            evaluation.level,
            evaluation.effective_price_per_person,
            self.config.meaningful_drop_ratio,
        ):
            return False
        if not getattr(self.notifier, "configured", True):
            logger.warning("PushPlus is not configured; leaving alert unsent")
            return False
        title = f"✈️ {quote.outbound[-1].destination} {evaluation.level.value}"
        try:
            self.notifier.send(title, _content(quote, evaluation), quote.booking_url)
        except Exception:
            logger.exception("notification failed signature=%s", quote.signature)
            return False
        return True
