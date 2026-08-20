from __future__ import annotations

from decimal import Decimal

from .domain import DealLevel


def level_rank(level: DealLevel | None) -> int:
    return {None: 0, DealLevel.GOOD: 1, DealLevel.GREAT: 2, DealLevel.EXCELLENT: 3}[level]


def classify(
    effective_price_per_person: Decimal,
    target_price: Decimal,
    historical_median: Decimal | None,
    historical_count: int,
    effective_hours: float,
) -> tuple[DealLevel | None, tuple[str, ...]]:
    reasons: list[str] = []
    excellent = effective_price_per_person <= target_price * Decimal("0.80")
    great = effective_price_per_person <= target_price
    good = (
        effective_price_per_person <= target_price * Decimal("1.10")
        and effective_hours >= 60
    )
    if historical_median is not None and historical_count >= 5:
        if effective_price_per_person <= historical_median * Decimal("0.75"):
            excellent = True
            reasons.append("PRICE_BELOW_75_PERCENT_OF_MEDIAN")
        elif effective_price_per_person <= historical_median * Decimal("0.85"):
            great = True
            reasons.append("PRICE_BELOW_85_PERCENT_OF_MEDIAN")
    if effective_price_per_person <= target_price:
        reasons.append("PRICE_AT_OR_BELOW_TARGET")
    elif good:
        reasons.append("PRICE_WITHIN_10_PERCENT_OF_TARGET")
    if effective_hours >= 72:
        reasons.append("EFFECTIVE_TRAVEL_OVER_72_HOURS")
    elif effective_hours >= 60:
        reasons.append("EFFECTIVE_TRAVEL_OVER_60_HOURS")
    if excellent:
        return DealLevel.EXCELLENT, tuple(reasons)
    if great:
        return DealLevel.GREAT, tuple(reasons)
    if good:
        return DealLevel.GOOD, tuple(reasons)
    return None, tuple(reasons)


def should_notify(
    previous_level: DealLevel | None,
    previous_price: Decimal | None,
    new_level: DealLevel,
    new_price: Decimal,
    meaningful_drop_ratio: Decimal,
) -> bool:
    if previous_level is None:
        return True
    if level_rank(new_level) > level_rank(previous_level):
        return True
    if previous_price is None or previous_price <= 0:
        return True
    return new_price <= previous_price * (Decimal("1") - meaningful_drop_ratio)
