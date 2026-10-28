from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

DATA_DIR = Path(__file__).parents[1] / "sample_data" / "synthetic"


def _read(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _total(rows: list[dict[str, str]], field: str) -> Decimal:
    return sum((Decimal(row[field]) for row in rows), start=Decimal(0))


def test_fixture_counts_keys_and_relationships():
    orders = _read("orders.csv")
    lines = _read("order_lines.csv")
    costs = _read("costs.csv")
    returns = _read("returns.csv")
    events = _read("process_events.csv")

    assert [len(orders), len(lines), len(costs), len(returns), len(events)] == [12, 12, 48, 3, 56]
    assert len({row["order_id"] for row in orders}) == len(orders)
    assert len({(row["order_id"], row["line_id"]) for row in lines}) == len(lines)
    assert len({row["cost_id"] for row in costs}) == len(costs)
    assert len({row["return_id"] for row in returns}) == len(returns)
    assert len({row["event_id"] for row in events}) == len(events)

    order_ids = {row["order_id"] for row in orders}
    assert {row["order_id"] for row in lines + costs + returns + events} <= order_ids


def test_financial_control_totals_reconcile():
    orders = _read("orders.csv")
    lines = _read("order_lines.csv")
    costs = _read("costs.csv")
    returns = _read("returns.csv")

    line_gross = sum((Decimal(row["quantity"]) * Decimal(row["unit_price"]) for row in lines), start=Decimal(0))
    assert line_gross == _total(orders, "gross_sales") == Decimal("2185000.00")
    assert _total(lines, "discount") == _total(orders, "discount") == Decimal("122000.00")
    assert _total(lines, "tax") == _total(orders, "tax") == Decimal("330080.00")

    refunds = _total(returns, "refunded_revenue")
    net_revenue = _total(orders, "gross_sales") - _total(orders, "discount") - refunds
    costs_by_category: dict[str, Decimal] = defaultdict(Decimal)
    for row in costs:
        costs_by_category[row["category"]] += Decimal(row["amount"])
    recognized_cogs = costs_by_category["cogs"] - _total(returns, "inventory_recovery_amount")
    variable_costs = sum(
        (costs_by_category[category] for category in ("shipping", "handling", "payment_fee")),
        start=Decimal(0),
    )

    assert refunds == Decimal("45000.00")
    assert net_revenue == Decimal("2018000.00")
    assert recognized_cogs == Decimal("1368000.00")
    assert variable_costs == Decimal("191000.00")
    assert net_revenue - recognized_cogs - variable_costs == Decimal("459000.00")


def test_seeded_process_signals_are_present():
    events = _read("process_events.csv")
    by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in events:
        by_order[event["order_id"]].append(event)

    loop_orders: set[str] = set()
    breach_orders: set[str] = set()
    for order_id, case_events in by_order.items():
        ordered = sorted(case_events, key=lambda row: (row["occurred_at"], row["event_id"]))
        activities = [row["activity"] for row in ordered]
        if any(
            activity == "Approval rejected" and "Approval requested" in activities[index + 1 :]
            for index, activity in enumerate(activities)
        ):
            loop_orders.add(order_id)
        started = next(
            datetime.fromisoformat(row["occurred_at"]) for row in ordered if row["activity"] == "Order received"
        )
        completed = next(
            datetime.fromisoformat(row["occurred_at"]) for row in ordered if row["activity"] == "Dispatched"
        )
        if (completed - started).total_seconds() > 48 * 3600:
            breach_orders.add(order_id)

    assert loop_orders == {"ORD-1002", "ORD-1006", "ORD-1010", "ORD-1011"}
    assert breach_orders == {"ORD-1002", "ORD-1006", "ORD-1009", "ORD-1010", "ORD-1011", "ORD-1012"}
