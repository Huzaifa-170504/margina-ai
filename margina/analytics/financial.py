from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")

METRIC_DEFINITIONS = {
    "net_revenue": "Gross sales minus discounts and refunded revenue; collected sales tax is excluded.",
    "gross_profit": "Net revenue minus recognized cost of goods sold under the approved costing policy.",
    "contribution": "Gross profit minus explicitly included variable fulfillment costs.",
    "contribution_margin": "Contribution divided by net revenue; undefined when net revenue is zero.",
}


@dataclass(frozen=True)
class FinancialRecord:
    order_id: str
    branch_id: str
    gross_sales: Decimal
    discount: Decimal
    refunded_revenue: Decimal
    cogs: Decimal
    variable_costs: Decimal


def calculate_financial_metrics(records: Iterable[FinancialRecord]) -> dict[str, Decimal | None]:
    rows = tuple(records)
    gross_sales = sum((row.gross_sales for row in rows), Decimal("0"))
    discounts = sum((row.discount for row in rows), Decimal("0"))
    refunds = sum((row.refunded_revenue for row in rows), Decimal("0"))
    cogs = sum((row.cogs for row in rows), Decimal("0"))
    variable_costs = sum((row.variable_costs for row in rows), Decimal("0"))

    net_revenue = gross_sales - discounts - refunds
    gross_profit = net_revenue - cogs
    contribution = gross_profit - variable_costs
    margin = None if net_revenue == 0 else contribution / net_revenue
    return {
        "gross_sales": _money(gross_sales),
        "discounts": _money(discounts),
        "refunded_revenue": _money(refunds),
        "net_revenue": _money(net_revenue),
        "cogs": _money(cogs),
        "variable_costs": _money(variable_costs),
        "gross_profit": _money(gross_profit),
        "contribution": _money(contribution),
        "contribution_margin": None if margin is None else margin.quantize(Decimal("0.0001")),
    }


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
