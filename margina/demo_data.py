from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from margina.analytics.financial import FinancialRecord
from margina.analytics.process import ProcessEvent

DEMO_SNAPSHOT_ID = "demo-snapshot-2026-10-v1"

FINANCIAL_RECORDS = (
    FinancialRecord(
        "ORD-1001", "Branch A", Decimal("180000"), Decimal("5000"), Decimal("0"), Decimal("119000"), Decimal("25000")
    ),
    FinancialRecord(
        "ORD-1002", "Branch A", Decimal("140000"), Decimal("12000"), Decimal("0"), Decimal("92000"), Decimal("24000")
    ),
    FinancialRecord(
        "ORD-1003", "Branch B", Decimal("210000"), Decimal("4000"), Decimal("0"), Decimal("142000"), Decimal("18000")
    ),
    FinancialRecord(
        "ORD-1004", "Branch B", Decimal("95000"), Decimal("15000"), Decimal("5000"), Decimal("61000"), Decimal("13000")
    ),
    FinancialRecord(
        "ORD-1005", "Branch C", Decimal("260000"), Decimal("6000"), Decimal("0"), Decimal("174000"), Decimal("21000")
    ),
    FinancialRecord(
        "ORD-1006", "Branch C", Decimal("175000"), Decimal("3000"), Decimal("0"), Decimal("116000"), Decimal("32000")
    ),
)

_START = datetime(2026, 8, 1, 9, tzinfo=UTC)
PROCESS_EVENTS = tuple(
    event
    for index, record in enumerate(FINANCIAL_RECORDS)
    for event in (
        ProcessEvent(f"EV-{index}-1", record.order_id, "Order received", _START + timedelta(days=index)),
        ProcessEvent(f"EV-{index}-2", record.order_id, "Approved", _START + timedelta(days=index, hours=4 + index * 3)),
        ProcessEvent(
            f"EV-{index}-3", record.order_id, "Dispatched", _START + timedelta(days=index, hours=22 + index * 4)
        ),
    )
)


def record_to_dict(record: FinancialRecord) -> dict[str, str]:
    return {
        "order_id": record.order_id,
        "branch_id": record.branch_id,
        "gross_sales": str(record.gross_sales),
        "discount": str(record.discount),
        "refunded_revenue": str(record.refunded_revenue),
        "cogs": str(record.cogs),
        "variable_costs": str(record.variable_costs),
    }
