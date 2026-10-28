from __future__ import annotations

from flask import Blueprint, jsonify, request

from margina.analytics.snapshot import SnapshotAnalyticsError, get_snapshot_analytics
from margina.auth.context import require_branch_access, require_tenant_access
from margina.errors import ApiError

workspace_api = Blueprint("workspace_api", __name__)


@workspace_api.get("/organizations/<tenant_id>/dashboard/summary")
def dashboard_summary(tenant_id: str):
    membership = require_tenant_access(tenant_id, {"finance", "analyst"})
    return jsonify(_analytics(tenant_id, membership.branch_scope).summary)


@workspace_api.get("/organizations/<tenant_id>/dashboard/orders")
def dashboard_orders(tenant_id: str):
    membership = require_tenant_access(tenant_id, {"finance", "analyst"})
    analytics = _analytics(tenant_id, membership.branch_scope)
    return jsonify({"snapshot_id": analytics.snapshot.snapshot_id, "orders": analytics.orders})


@workspace_api.get("/organizations/<tenant_id>/dashboard/process")
def dashboard_process(tenant_id: str):
    membership = require_tenant_access(tenant_id, {"finance", "operations", "analyst", "administrator"})
    analytics = _analytics(tenant_id, membership.branch_scope)
    return jsonify(
        {
            "snapshot_id": analytics.snapshot.snapshot_id,
            "available_branches": analytics.summary["available_branches"],
            **analytics.process,
        }
    )


def _analytics(tenant_id: str, branch_scope: list[str]):
    branch = request.args.get("branch", "").strip()
    if branch:
        require_branch_access(tenant_id, branch)
    try:
        return get_snapshot_analytics(
            tenant_id,
            branch_id=branch or None,
            allowed_branches=None if not branch_scope else set(branch_scope),
        )
    except SnapshotAnalyticsError as error:
        raise ApiError(error.message, error.status_code, error.code) from error
