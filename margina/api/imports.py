from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify

from margina.auth.context import require_csrf, require_tenant_access, require_user
from margina.errors import ApiError
from margina.imports.service import (
    ImportOutcome,
    WorkflowError,
    approve_snapshot,
    get_import,
    get_snapshot,
    import_directory,
    publish_snapshot,
)
from margina.models import ImportBatch, Snapshot

imports_api = Blueprint("imports_api", __name__)
SYNTHETIC_TENANT_ID = "demo-distributor"


@imports_api.post("/imports/synthetic")
def import_synthetic():
    require_csrf()
    actor = require_user()
    require_tenant_access(SYNTHETIC_TENANT_ID, {"administrator"}, require_full_scope=True)
    if not current_app.config["DEMO_ENABLED"]:
        raise ApiError("The synthetic import is disabled.", 404, "demo_disabled")
    fixture_directory = Path(current_app.root_path).parent / "sample_data" / "synthetic"
    outcome = _workflow_call(
        import_directory,
        fixture_directory,
        "bundled://sample_data/synthetic",
        actor.user_id,
    )
    status_code = 200 if outcome.idempotent_replay else (422 if outcome.import_batch.status == "quarantined" else 201)
    return jsonify(_outcome_payload(outcome)), status_code


@imports_api.get("/imports/<import_id>")
def import_status(import_id: str):
    require_user()
    batch, snapshot = _workflow_call(get_import, import_id)
    require_tenant_access(
        batch.tenant_id,
        {"finance", "analyst", "administrator"},
        require_full_scope=True,
    )
    return jsonify(
        {"import": _import_payload(batch), "snapshot": None if snapshot is None else _snapshot_payload(snapshot)}
    )


@imports_api.get("/snapshots/<snapshot_id>")
def snapshot_status(snapshot_id: str):
    require_user()
    snapshot = _workflow_call(get_snapshot, snapshot_id)
    require_tenant_access(snapshot.tenant_id, {"finance", "operations", "analyst", "administrator"})
    return jsonify({"snapshot": _snapshot_payload(snapshot)})


@imports_api.post("/snapshots/<snapshot_id>/approve")
def snapshot_approve(snapshot_id: str):
    require_csrf()
    actor = require_user()
    snapshot = _workflow_call(get_snapshot, snapshot_id)
    require_tenant_access(snapshot.tenant_id, {"finance"}, require_full_scope=True)
    snapshot, idempotent = _workflow_call(approve_snapshot, snapshot_id, actor.user_id)
    return jsonify({"snapshot": _snapshot_payload(snapshot), "idempotent_replay": idempotent})


@imports_api.post("/snapshots/<snapshot_id>/publish")
def snapshot_publish(snapshot_id: str):
    require_csrf()
    actor = require_user()
    snapshot = _workflow_call(get_snapshot, snapshot_id)
    require_tenant_access(snapshot.tenant_id, {"administrator"}, require_full_scope=True)
    snapshot, idempotent = _workflow_call(publish_snapshot, snapshot_id, actor.user_id)
    return jsonify({"snapshot": _snapshot_payload(snapshot), "idempotent_replay": idempotent})


def _workflow_call(function, *args):
    try:
        return function(*args)
    except WorkflowError as error:
        raise ApiError(error.message, error.status_code, error.code) from error


def _outcome_payload(outcome: ImportOutcome) -> dict[str, object]:
    return {
        "import": _import_payload(outcome.import_batch),
        "snapshot": None if outcome.snapshot is None else _snapshot_payload(outcome.snapshot),
        "idempotent_replay": outcome.idempotent_replay,
    }


def _import_payload(batch: ImportBatch) -> dict[str, object]:
    return {
        "import_id": batch.import_id,
        "tenant_id": batch.tenant_id,
        "source_system": batch.source_system,
        "dataset_hash": batch.source_file_hash,
        "mapping_version": batch.mapping_version,
        "status": batch.status,
        "accepted_count": batch.accepted_count,
        "rejected_count": batch.rejected_count,
        "duplicate_count": batch.duplicate_count,
        "control_totals": batch.control_totals,
        "row_errors": batch.row_errors,
    }


def _snapshot_payload(snapshot: Snapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "tenant_id": snapshot.tenant_id,
        "import_id": snapshot.import_id,
        "metric_version": snapshot.metric_version,
        "status": snapshot.status,
        "limitations": snapshot.limitations,
        "approved_at": None if snapshot.approved_at is None else snapshot.approved_at.isoformat(),
        "approved_by": snapshot.approved_by,
        "published_at": None if snapshot.published_at is None else snapshot.published_at.isoformat(),
        "published_by": snapshot.published_by,
    }
