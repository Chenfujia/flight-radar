from decimal import Decimal

from flight_radar.deals import classify, should_notify
from flight_radar.domain import DealLevel


def test_classify_without_history():
    level, reasons = classify(
        Decimal("1200"), Decimal("1650"), None, 0, 80
    )
    assert level is DealLevel.EXCELLENT
    assert "PRICE_AT_OR_BELOW_TARGET" in reasons


def test_classify_good_requires_effective_time():
    level, _ = classify(Decimal("1700"), Decimal("1650"), None, 0, 50)
    assert level is None


def test_notification_only_on_upgrade_or_meaningful_drop():
    assert not should_notify(
        DealLevel.GREAT, Decimal("1500"), DealLevel.GREAT, Decimal("1450"), Decimal("0.05")
    )
    assert should_notify(
        DealLevel.GREAT, Decimal("1500"), DealLevel.GREAT, Decimal("1420"), Decimal("0.05")
    )
    assert should_notify(
        DealLevel.GOOD, Decimal("1500"), DealLevel.GREAT, Decimal("1500"), Decimal("0.05")
    )
