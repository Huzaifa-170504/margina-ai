from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_FILE_BYTES: Final = 20 * 1024 * 1024
MAX_ROWS_PER_FILE: Final = 50_000

FILE_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "orders.csv": (
        "tenant_id",
        "source_system",
        "order_id",
        "customer_id",
        "branch_id",
        "currency",
        "occurred_at",
        "original_timezone",
        "gross_sales",
        "discount",
        "tax",
        "source_reference",
    ),
    "order_lines.csv": (
        "tenant_id",
        "source_system",
        "order_id",
        "line_id",
        "product_id",
        "quantity",
        "unit_price",
        "discount",
        "tax",
        "currency",
        "occurred_at",
        "original_timezone",
        "source_reference",
    ),
    "costs.csv": (
        "tenant_id",
        "source_system",
        "cost_id",
        "order_id",
        "line_id",
        "category",
        "amount",
        "currency",
        "effective_at",
        "original_timezone",
        "included_in_contribution",
        "source_reference",
    ),
    "returns.csv": (
        "tenant_id",
        "source_system",
        "return_id",
        "order_id",
        "line_id",
        "refunded_revenue",
        "inventory_recovery_amount",
        "currency",
        "effective_at",
        "original_timezone",
        "source_reference",
    ),
    "process_events.csv": (
        "tenant_id",
        "source_system",
        "event_id",
        "order_id",
        "activity",
        "lifecycle_marker",
        "occurred_at",
        "ingested_at",
        "original_timezone",
        "source_reference",
    ),
}

OPTIONAL_FIELDS: Final = {
    ("costs.csv", "line_id"),
    ("returns.csv", "line_id"),
    ("process_events.csv", "lifecycle_marker"),
}


@dataclass(frozen=True)
class DatasetIdentity:
    tenant_id: str
    source_system: str
    currency: str
    reporting_timezone: str


@dataclass(frozen=True)
class ValidatedDataset:
    files: dict[str, bytes]
    rows: dict[str, list[dict[str, str]]]
    identity: DatasetIdentity
    dataset_hash: str
    control_totals: dict[str, object]

    @property
    def accepted_count(self) -> int:
        return sum(len(rows) for rows in self.rows.values())


class DatasetValidationError(Exception):
    def __init__(
        self,
        errors: list[dict[str, object]],
        dataset_hash: str,
        identity: DatasetIdentity | None,
    ) -> None:
        super().__init__("Dataset validation failed.")
        self.errors = errors
        self.dataset_hash = dataset_hash
        self.identity = identity


def files_from_directory(directory: Path) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in FILE_HEADERS}


def validate_dataset(files: dict[str, bytes]) -> ValidatedDataset:
    dataset_hash = _dataset_hash(files)
    errors: list[dict[str, object]] = []
    rows = _parse_csv_files(files, errors)
    identity = _extract_identity(rows)

    if not errors:
        _validate_rows(rows, identity, errors)
    if errors:
        raise DatasetValidationError(errors, dataset_hash, identity)
    if identity is None:  # Defensive: row validation requires an identity.
        raise DatasetValidationError(
            [_error("orders.csv", 1, "tenant_id", "missing_identity", "Missing identity.")], dataset_hash, None
        )

    return ValidatedDataset(
        files=dict(files),
        rows=rows,
        identity=identity,
        dataset_hash=dataset_hash,
        control_totals=_control_totals(rows),
    )


def _dataset_hash(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[name])
        digest.update(b"\0")
    return digest.hexdigest()


def _parse_csv_files(files: dict[str, bytes], errors: list[dict[str, object]]) -> dict[str, list[dict[str, str]]]:
    parsed: dict[str, list[dict[str, str]]] = {}
    missing = sorted(set(FILE_HEADERS) - set(files))
    unexpected = sorted(set(files) - set(FILE_HEADERS))
    for name in missing:
        errors.append(_error(name, 1, None, "missing_file", "Required CSV file is missing."))
    for name in unexpected:
        errors.append(_error(name, 1, None, "unexpected_file", "Unexpected CSV file."))

    for name, expected_headers in FILE_HEADERS.items():
        content = files.get(name)
        if content is None:
            parsed[name] = []
            continue
        if len(content) > MAX_FILE_BYTES:
            errors.append(_error(name, 1, None, "file_too_large", "CSV exceeds the 20 MB limit."))
            parsed[name] = []
            continue
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            errors.append(_error(name, 1, None, "invalid_encoding", "CSV must be UTF-8 encoded."))
            parsed[name] = []
            continue

        reader = csv.DictReader(io.StringIO(text, newline=""))
        actual_headers = tuple(reader.fieldnames or ())
        if actual_headers != expected_headers:
            errors.append(
                _error(
                    name,
                    1,
                    None,
                    "invalid_headers",
                    "Headers must exactly match the documented schema and order.",
                    {"expected": list(expected_headers), "actual": list(actual_headers)},
                )
            )
            parsed[name] = []
            continue
        file_rows = list(reader)
        if len(file_rows) > MAX_ROWS_PER_FILE:
            errors.append(_error(name, 1, None, "too_many_rows", "CSV exceeds the 50,000-row limit."))
            file_rows = file_rows[:MAX_ROWS_PER_FILE]
        if not file_rows:
            errors.append(_error(name, 1, None, "empty_file", "CSV must include at least one data row."))
        for row_number, row in enumerate(file_rows, start=2):
            row["_row_number"] = str(row_number)
        parsed[name] = file_rows
    return parsed


def _extract_identity(rows: dict[str, list[dict[str, str]]]) -> DatasetIdentity | None:
    first = next(iter(rows.get("orders.csv", [])), None)
    if first is None:
        return None
    values = (
        first.get("tenant_id", ""),
        first.get("source_system", ""),
        first.get("currency", ""),
        first.get("original_timezone", ""),
    )
    if not all(values):
        return None
    return DatasetIdentity(*values)


def _validate_rows(
    rows: dict[str, list[dict[str, str]]],
    identity: DatasetIdentity | None,
    errors: list[dict[str, object]],
) -> None:
    if identity is None:
        errors.append(
            _error("orders.csv", 2, "tenant_id", "missing_identity", "A complete dataset identity is required.")
        )
        return

    decimal_fields = {
        "orders.csv": ("gross_sales", "discount", "tax"),
        "order_lines.csv": ("quantity", "unit_price", "discount", "tax"),
        "costs.csv": ("amount",),
        "returns.csv": ("refunded_revenue", "inventory_recovery_amount"),
    }
    timestamp_fields = {
        "orders.csv": ("occurred_at",),
        "order_lines.csv": ("occurred_at",),
        "costs.csv": ("effective_at",),
        "returns.csv": ("effective_at",),
        "process_events.csv": ("occurred_at", "ingested_at"),
    }
    unique_fields = {
        "orders.csv": ("order_id",),
        "order_lines.csv": ("order_id", "line_id"),
        "costs.csv": ("cost_id",),
        "returns.csv": ("return_id",),
        "process_events.csv": ("event_id",),
    }

    for file_name, file_rows in rows.items():
        seen: set[tuple[str, ...]] = set()
        for row in file_rows:
            row_number = int(row["_row_number"])
            for field in FILE_HEADERS[file_name]:
                if not row.get(field, "").strip() and (file_name, field) not in OPTIONAL_FIELDS:
                    errors.append(_error(file_name, row_number, field, "required", "Value is required."))
            if row.get("tenant_id") != identity.tenant_id:
                errors.append(
                    _error(file_name, row_number, "tenant_id", "mixed_tenant", "All rows must use one tenant.")
                )
            if row.get("source_system") != identity.source_system:
                errors.append(
                    _error(
                        file_name, row_number, "source_system", "mixed_source", "All rows must use one source system."
                    )
                )
            if "currency" in row and row.get("currency") != identity.currency:
                errors.append(
                    _error(
                        file_name, row_number, "currency", "mixed_currency", "Currency conversion is outside the MVP."
                    )
                )
            if row.get("original_timezone") != identity.reporting_timezone:
                errors.append(
                    _error(
                        file_name,
                        row_number,
                        "original_timezone",
                        "mixed_timezone",
                        "All rows must use one reporting timezone.",
                    )
                )
            for field in decimal_fields.get(file_name, ()):
                _decimal(row.get(field), file_name, row_number, field, errors)
            for field in timestamp_fields.get(file_name, ()):
                _utc_datetime(row.get(field), file_name, row_number, field, errors)
            key = tuple(row.get(field, "") for field in unique_fields[file_name])
            if key in seen:
                errors.append(_error(file_name, row_number, None, "duplicate_key", f"Duplicate business key: {key!r}."))
            seen.add(key)

    try:
        ZoneInfo(identity.reporting_timezone)
    except ZoneInfoNotFoundError:
        errors.append(_error("orders.csv", 2, "original_timezone", "invalid_timezone", "Unknown IANA timezone."))
    if errors:
        return

    orders = {row["order_id"]: row for row in rows["orders.csv"]}
    line_keys = {(row["order_id"], row["line_id"]) for row in rows["order_lines.csv"]}
    for file_name in ("order_lines.csv", "costs.csv", "returns.csv", "process_events.csv"):
        for row in rows[file_name]:
            if row["order_id"] not in orders:
                errors.append(
                    _error(
                        file_name,
                        int(row["_row_number"]),
                        "order_id",
                        "missing_order",
                        "Referenced order does not exist.",
                    )
                )
            line_id = row.get("line_id", "")
            if line_id and (row["order_id"], line_id) not in line_keys:
                errors.append(
                    _error(
                        file_name,
                        int(row["_row_number"]),
                        "line_id",
                        "missing_line",
                        "Referenced order line does not exist.",
                    )
                )

    line_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows["order_lines.csv"]:
        line_totals[row["order_id"]]["gross_sales"] += Decimal(row["quantity"]) * Decimal(row["unit_price"])
        line_totals[row["order_id"]]["discount"] += Decimal(row["discount"])
        line_totals[row["order_id"]]["tax"] += Decimal(row["tax"])
    for order_id, order in orders.items():
        for field in ("gross_sales", "discount", "tax"):
            if line_totals[order_id][field] != Decimal(order[field]):
                errors.append(
                    _error(
                        "orders.csv",
                        int(order["_row_number"]),
                        field,
                        "control_mismatch",
                        f"Order value does not reconcile to lines for {order_id}.",
                    )
                )

    allowed_categories = {"cogs", "shipping", "handling", "payment_fee"}
    cogs_orders: set[str] = set()
    for row in rows["costs.csv"]:
        if row["category"] not in allowed_categories:
            errors.append(
                _error(
                    "costs.csv",
                    int(row["_row_number"]),
                    "category",
                    "invalid_category",
                    "Cost category is not approved.",
                )
            )
        if row["included_in_contribution"].lower() not in {"true", "false"}:
            errors.append(
                _error(
                    "costs.csv",
                    int(row["_row_number"]),
                    "included_in_contribution",
                    "invalid_boolean",
                    "Use true or false.",
                )
            )
        if row["category"] == "cogs":
            cogs_orders.add(row["order_id"])
    for order_id in orders.keys() - cogs_orders:
        errors.append(
            _error(
                "costs.csv",
                1,
                "category",
                "missing_cogs",
                f"{order_id} has no recognized COGS row; contribution cannot be published.",
            )
        )

    base_cogs = sum(
        (Decimal(row["amount"]) for row in rows["costs.csv"] if row["category"] == "cogs"),
        start=Decimal(0),
    )
    inventory_recovery = _sum(rows["returns.csv"], "inventory_recovery_amount")
    if inventory_recovery > base_cogs:
        errors.append(
            _error(
                "returns.csv",
                1,
                "inventory_recovery_amount",
                "recovery_exceeds_cogs",
                "Inventory recovery cannot exceed base COGS.",
            )
        )

    events_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows["process_events.csv"]:
        occurred = datetime.fromisoformat(row["occurred_at"])
        ingested = datetime.fromisoformat(row["ingested_at"])
        if ingested < occurred:
            errors.append(
                _error(
                    "process_events.csv",
                    int(row["_row_number"]),
                    "ingested_at",
                    "ingested_before_event",
                    "Ingestion cannot precede the source event.",
                )
            )
        events_by_order[row["order_id"]].append(row)
    for order_id in orders:
        activities = {row["activity"] for row in events_by_order[order_id]}
        if "Order received" not in activities or "Dispatched" not in activities:
            errors.append(
                _error(
                    "process_events.csv",
                    1,
                    "activity",
                    "incomplete_case",
                    f"{order_id} requires start and completion events.",
                )
            )


def _decimal(
    value: str | None,
    file_name: str,
    row_number: int,
    field: str,
    errors: list[dict[str, object]],
) -> Decimal | None:
    try:
        parsed = Decimal(value or "")
    except InvalidOperation:
        errors.append(_error(file_name, row_number, field, "invalid_decimal", "A decimal number is required."))
        return None
    if not parsed.is_finite() or parsed < 0:
        errors.append(_error(file_name, row_number, field, "invalid_decimal", "Value must be finite and non-negative."))
        return None
    return parsed


def _utc_datetime(
    value: str | None,
    file_name: str,
    row_number: int,
    field: str,
    errors: list[dict[str, object]],
) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError:
        errors.append(
            _error(file_name, row_number, field, "invalid_timestamp", "Use an ISO 8601 timestamp with UTC offset.")
        )
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        errors.append(_error(file_name, row_number, field, "non_utc_timestamp", "Timestamp must be UTC."))
        return None
    return parsed


def _control_totals(rows: dict[str, list[dict[str, str]]]) -> dict[str, object]:
    orders = rows["orders.csv"]
    costs = rows["costs.csv"]
    returns = rows["returns.csv"]
    gross_sales = _sum(orders, "gross_sales")
    discounts = _sum(orders, "discount")
    refunded_revenue = _sum(returns, "refunded_revenue")
    net_revenue = gross_sales - discounts - refunded_revenue
    by_category: dict[str, Decimal] = defaultdict(Decimal)
    included_by_category: dict[str, Decimal] = defaultdict(Decimal)
    for row in costs:
        amount = Decimal(row["amount"])
        by_category[row["category"]] += amount
        if row["included_in_contribution"].lower() == "true":
            included_by_category[row["category"]] += amount
    inventory_recovery = _sum(returns, "inventory_recovery_amount")
    recognized_cogs = by_category["cogs"] - inventory_recovery
    variable_costs = (
        included_by_category["shipping"] + included_by_category["handling"] + included_by_category["payment_fee"]
    )
    contribution = net_revenue - recognized_cogs - variable_costs
    margin = None if net_revenue == 0 else contribution / net_revenue

    return {
        "row_counts": {name: len(file_rows) for name, file_rows in rows.items()},
        "gross_sales": _text(gross_sales),
        "discounts": _text(discounts),
        "sales_tax": _text(_sum(orders, "tax")),
        "refunded_revenue": _text(refunded_revenue),
        "net_revenue": _text(net_revenue),
        "base_cogs": _text(by_category["cogs"]),
        "inventory_recovery": _text(inventory_recovery),
        "recognized_cogs": _text(recognized_cogs),
        "shipping": _text(by_category["shipping"]),
        "handling": _text(by_category["handling"]),
        "payment_fees": _text(by_category["payment_fee"]),
        "variable_costs": _text(variable_costs),
        "gross_profit": _text(net_revenue - recognized_cogs),
        "contribution": _text(contribution),
        "contribution_margin": None if margin is None else str(margin.quantize(Decimal("0.000001"))),
    }


def _sum(rows: list[dict[str, str]], field: str) -> Decimal:
    return sum((Decimal(row[field]) for row in rows), start=Decimal(0))


def _text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _error(
    file_name: str,
    row: int,
    field: str | None,
    code: str,
    message: str,
    context: object | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {"file": file_name, "row": row, "field": field, "code": code, "message": message}
    if context is not None:
        error["context"] = context
    return error
