from datetime import UTC, datetime, timedelta
from decimal import Decimal

from margina.analytics.financial import FinancialRecord, calculate_financial_metrics
from margina.analytics.process import ProcessEvent, directly_follows


def test_financial_metrics_reconcile():
    metrics = calculate_financial_metrics(
        [FinancialRecord("1", "A", Decimal("100"), Decimal("10"), Decimal("5"), Decimal("40"), Decimal("15"))]
    )
    assert metrics["net_revenue"] == Decimal("85.00")
    assert metrics["contribution"] == Decimal("30.00")
    assert metrics["contribution_margin"] == Decimal("0.3529")


def test_zero_revenue_has_undefined_margin():
    metrics = calculate_financial_metrics(
        [FinancialRecord("1", "A", Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))]
    )
    assert metrics["contribution_margin"] is None


def test_process_events_are_ordered_deterministically():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    transitions = directly_follows(
        [
            ProcessEvent("b", "1", "Approved", start + timedelta(hours=2)),
            ProcessEvent("a", "1", "Received", start),
            ProcessEvent("c", "1", "Dispatched", start + timedelta(hours=5)),
        ]
    )
    assert transitions == [
        {"from": "Approved", "to": "Dispatched", "count": 1, "median_hours": 3.0},
        {"from": "Received", "to": "Approved", "count": 1, "median_hours": 2.0},
    ]
