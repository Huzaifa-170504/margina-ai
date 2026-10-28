from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request, session

from margina.analytics.snapshot import SnapshotAnalyticsError, get_snapshot_analytics
from margina.errors import ApiError

demo_api = Blueprint("demo_api", __name__)


@demo_api.before_request
def ensure_demo_enabled():
    if not current_app.config["DEMO_ENABLED"]:
        raise ApiError("The public demo is disabled.", 404, "demo_disabled")


@demo_api.get("/summary")
def summary():
    branch = request.args.get("branch", "").strip()
    return jsonify(_analytics(branch).summary)


@demo_api.get("/orders")
def orders():
    branch = request.args.get("branch", "").strip()
    analytics = _analytics(branch)
    return jsonify({"synthetic": True, "snapshot_id": analytics.snapshot.snapshot_id, "orders": analytics.orders})


@demo_api.get("/process")
def process_map():
    branch = request.args.get("branch", "").strip()
    analytics = _analytics(branch)
    return jsonify({"synthetic": True, "snapshot_id": analytics.snapshot.snapshot_id, **analytics.process})


@demo_api.post("/scenarios/shipping")
def shipping_scenario():
    body = request.get_json(silent=True) or {}
    shipment_count = _bounded_int(body.get("shipment_count"), "shipment_count", 0, 50_000)
    saving_per_shipment = _bounded_decimal(
        body.get("saving_per_shipment"), "saving_per_shipment", Decimal("0"), Decimal("1000000")
    )
    incremental_cost = _bounded_decimal(
        body.get("incremental_cost", 0), "incremental_cost", Decimal("0"), Decimal("1000000000")
    )
    analytics = _analytics("")
    gross_savings = Decimal(shipment_count) * saving_per_shipment
    result = {
        "shipment_count": shipment_count,
        "saving_per_shipment": str(saving_per_shipment),
        "incremental_cost": str(incremental_cost),
        "gross_savings": str(gross_savings),
        "estimated_net_savings": str(gross_savings - incremental_cost),
    }
    session["demo_shipping_scenario"] = result
    return jsonify(
        {
            "synthetic": True,
            "snapshot_id": analytics.snapshot.snapshot_id,
            "scenario": result,
            "disclaimer": "Modeled estimate based on user assumptions; not proven recoverable profit.",
        }
    )


@demo_api.post("/reset")
def reset():
    session.pop("demo_shipping_scenario", None)
    return jsonify({"reset": True, "scope": "current_demo_session"})


def _bounded_int(value, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ApiError(f"{field} must be an integer.", 422, "validation_error")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ApiError(f"{field} must be an integer.", 422, "validation_error") from error
    if parsed < minimum or parsed > maximum:
        raise ApiError(f"{field} must be between {minimum} and {maximum}.", 422, "validation_error")
    return parsed


def _bounded_decimal(value, field: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ApiError(f"{field} must be a decimal number.", 422, "validation_error") from error
    if not parsed.is_finite() or parsed < minimum or parsed > maximum:
        raise ApiError(f"{field} is outside the allowed range.", 422, "validation_error")
    return parsed.quantize(Decimal("0.01"))


def _analytics(branch: str):
    try:
        return get_snapshot_analytics("demo-distributor", branch_id=branch or None)
    except SnapshotAnalyticsError as error:
        raise ApiError(error.message, error.status_code, error.code) from error
