from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import ceil
from statistics import median

from sqlalchemy import select

from margina.analytics.financial import FinancialRecord, calculate_financial_metrics
from margina.analytics.process import ProcessEvent, directly_follows
from margina.extensions import db
from margina.models import CostRecord, Order, OrderEvent, OrderLine, ReturnRecord, Snapshot

VARIABLE_COST_CATEGORIES = frozenset({"shipping", "handling", "payment_fee"})


class SnapshotAnalyticsError(Exception):
    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class SnapshotAnalytics:
    snapshot: Snapshot
    summary: dict[str, object]
    orders: list[dict[str, object]]
    process: dict[str, object]


def get_snapshot_analytics(
    tenant_id: str,
    *,
    branch_id: str | None = None,
    allowed_branches: set[str] | None = None,
) -> SnapshotAnalytics:
    snapshot = db.session.scalar(
        select(Snapshot)
        .where(Snapshot.tenant_id == tenant_id, Snapshot.status == "published")
        .order_by(Snapshot.published_at.desc())
        .limit(1)
    )
    if snapshot is None:
        raise SnapshotAnalyticsError(
            "No published snapshot is available for this organization.",
            "published_snapshot_unavailable",
            503,
        )

    all_orders = list(
        db.session.scalars(
            select(Order).where(Order.tenant_id == tenant_id, Order.snapshot_id == snapshot.snapshot_id)
        ).all()
    )
    authorized_orders = [
        order for order in all_orders if allowed_branches is None or order.branch_id in allowed_branches
    ]
    available_branches = sorted({order.branch_id for order in authorized_orders})
    if branch_id is not None and branch_id not in available_branches:
        raise SnapshotAnalyticsError("Unknown or unauthorized branch filter.", "invalid_filter", 400)
    selected_orders = [order for order in authorized_orders if branch_id is None or order.branch_id == branch_id]
    selected_ids = {order.order_id for order in selected_orders}

    lines = _rows(OrderLine, tenant_id, snapshot.snapshot_id, selected_ids)
    costs = _rows(CostRecord, tenant_id, snapshot.snapshot_id, selected_ids)
    returns = _rows(ReturnRecord, tenant_id, snapshot.snapshot_id, selected_ids)
    events = _rows(OrderEvent, tenant_id, snapshot.snapshot_id, selected_ids)
    order_evidence = _order_evidence(selected_orders, lines, costs, returns, events)
    financial_records = [
        FinancialRecord(
            order_id=row["order_id"],
            branch_id=row["branch_id"],
            gross_sales=Decimal(row["gross_sales"]),
            discount=Decimal(row["discount"]),
            refunded_revenue=Decimal(row["refunded_revenue"]),
            cogs=Decimal(row["recognized_cogs"]),
            variable_costs=Decimal(row["variable_costs"]),
        )
        for row in order_evidence
    ]
    metrics = calculate_financial_metrics(financial_records)
    process = _process_summary(events, selected_orders)
    cogs_order_ids = {cost.order_id for cost in costs if cost.category == "cogs"}
    cost_coverage = 0 if not selected_orders else round(100 * len(cogs_order_ids) / len(selected_orders), 1)
    latest_source_event = max((event.occurred_at for event in events), default=None)
    latest_ingested = max((event.ingested_at for event in events), default=None)

    summary = {
        "synthetic": tenant_id == "demo-distributor",
        "snapshot_id": snapshot.snapshot_id,
        "metric_version": snapshot.metric_version,
        "snapshot_status": snapshot.status,
        "published_at": _timestamp(snapshot.published_at),
        "filters": {"branch": branch_id},
        "available_branches": available_branches,
        "coverage": {
            "financial_orders": len(selected_orders),
            "cost_coverage_percent": cost_coverage,
            "process_coverage_percent": process["coverage_percent"],
        },
        "freshness": {
            "latest_source_event_at": _timestamp(latest_source_event),
            "latest_ingested_at": _timestamp(latest_ingested),
            "published_at": _timestamp(snapshot.published_at),
        },
        "metrics": _decimal_payload(metrics),
        "process": {
            "median_cycle_hours": process["median_cycle_hours"],
            "p90_cycle_hours": process["p90_cycle_hours"],
            "sla_breach_count": process["sla_breach_count"],
            "approval_loop_count": process["approval_loop_count"],
        },
    }
    return SnapshotAnalytics(snapshot=snapshot, summary=summary, orders=order_evidence, process=process)


def _rows(model, tenant_id: str, snapshot_id: str, order_ids: set[str]):
    if not order_ids:
        return []
    return list(
        db.session.scalars(
            select(model).where(
                model.tenant_id == tenant_id,
                model.snapshot_id == snapshot_id,
                model.order_id.in_(order_ids),
            )
        ).all()
    )


def _order_evidence(
    orders: list[Order],
    lines: list[OrderLine],
    costs: list[CostRecord],
    returns: list[ReturnRecord],
    events: list[OrderEvent],
) -> list[dict[str, object]]:
    line_values: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for line in lines:
        line_values[line.order_id]["gross_sales"] += line.quantity * line.unit_price
        line_values[line.order_id]["discount"] += line.discount

    cost_values: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for cost in costs:
        if cost.category == "cogs":
            cost_values[cost.order_id]["base_cogs"] += cost.amount
        elif cost.included_in_contribution and cost.category in VARIABLE_COST_CATEGORIES:
            cost_values[cost.order_id]["variable_costs"] += cost.amount
            if cost.category == "shipping":
                cost_values[cost.order_id]["shipping"] += cost.amount

    return_values: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for return_record in returns:
        return_values[return_record.order_id]["refunded_revenue"] += return_record.refunded_revenue
        return_values[return_record.order_id]["inventory_recovery"] += return_record.inventory_recovery_amount

    events_by_order: dict[str, list[OrderEvent]] = defaultdict(list)
    for event in events:
        events_by_order[event.order_id].append(event)

    result: list[dict[str, object]] = []
    for order in sorted(orders, key=lambda item: (item.occurred_at, item.order_id), reverse=True):
        gross_sales = line_values[order.order_id]["gross_sales"]
        discount = line_values[order.order_id]["discount"]
        refunded_revenue = return_values[order.order_id]["refunded_revenue"]
        base_cogs = cost_values[order.order_id]["base_cogs"]
        inventory_recovery = return_values[order.order_id]["inventory_recovery"]
        recognized_cogs = base_cogs - inventory_recovery
        variable_costs = cost_values[order.order_id]["variable_costs"]
        net_revenue = gross_sales - discount - refunded_revenue
        contribution = net_revenue - recognized_cogs - variable_costs
        cycle_hours, approval_loop, completed = _case_metrics(events_by_order[order.order_id])
        result.append(
            {
                "order_id": order.order_id,
                "branch_id": order.branch_id,
                "occurred_at": _timestamp(order.occurred_at),
                "currency": order.currency,
                "gross_sales": _money(gross_sales),
                "discount": _money(discount),
                "refunded_revenue": _money(refunded_revenue),
                "net_revenue": _money(net_revenue),
                "base_cogs": _money(base_cogs),
                "inventory_recovery": _money(inventory_recovery),
                "recognized_cogs": _money(recognized_cogs),
                "shipping": _money(cost_values[order.order_id]["shipping"]),
                "variable_costs": _money(variable_costs),
                "contribution": _money(contribution),
                "cycle_hours": cycle_hours,
                "completed": completed,
                "approval_loop": approval_loop,
                "sla_breach": cycle_hours is not None and cycle_hours > 48,
                "source_reference": order.source_reference,
            }
        )
    return result


def _process_summary(events: list[OrderEvent], orders: list[Order]) -> dict[str, object]:
    process_events = [
        ProcessEvent(event.event_id, event.order_id, event.activity, event.occurred_at) for event in events
    ]
    by_order: dict[str, list[OrderEvent]] = defaultdict(list)
    for event in events:
        by_order[event.order_id].append(event)
    cycles: list[float] = []
    loop_count = 0
    breach_count = 0
    completed_count = 0
    for order in orders:
        cycle, loop, completed = _case_metrics(by_order[order.order_id])
        if loop:
            loop_count += 1
        if completed:
            completed_count += 1
        if cycle is not None:
            cycles.append(cycle)
            if cycle > 48:
                breach_count += 1
    coverage = 0 if not orders else round(100 * completed_count / len(orders), 1)
    return {
        "case_count": len(orders),
        "completed_case_count": completed_count,
        "incomplete_case_count": len(orders) - completed_count,
        "coverage_percent": coverage,
        "median_cycle_hours": None if not cycles else round(median(cycles), 2),
        "p90_cycle_hours": _percentile(cycles, 0.9),
        "sla_breach_count": breach_count,
        "approval_loop_count": loop_count,
        "transitions": directly_follows(process_events),
        "limitation": (
            "Elapsed timestamps measure waiting plus processing; they do not measure staff effort or prove causation."
        ),
    }


def _case_metrics(events: list[OrderEvent]) -> tuple[float | None, bool, bool]:
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_id))
    start = next((event.occurred_at for event in ordered if event.activity == "Order received"), None)
    end = next(
        (
            event.occurred_at
            for event in ordered
            if event.activity == "Dispatched" and (start is None or event.occurred_at >= start)
        ),
        None,
    )
    activities = [event.activity for event in ordered]
    approval_loop = any(
        activity == "Approval rejected" and "Approval requested" in activities[index + 1 :]
        for index, activity in enumerate(activities)
    )
    cycle = None if start is None or end is None else round((end - start).total_seconds() / 3600, 2)
    return cycle, approval_loop, start is not None and end is not None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 2)


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _decimal_payload(values: dict[str, Decimal | None]) -> dict[str, str | None]:
    return {key: None if value is None else str(value) for key, value in values.items()}


def _timestamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
