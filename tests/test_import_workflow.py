from pathlib import Path

from sqlalchemy import func, select

from margina.extensions import db
from margina.imports.service import import_directory, import_files
from margina.imports.validation import files_from_directory
from margina.models import CostRecord, ImportBatch, Order, OrderEvent, OrderLine, ReturnRecord, Snapshot

FIXTURE_DIRECTORY = Path(__file__).parents[1] / "sample_data" / "synthetic"


def _count(model) -> int:
    return db.session.scalar(select(func.count()).select_from(model)) or 0


def test_import_persists_reconciled_draft_and_is_idempotent(app):
    with app.app_context():
        first = import_directory(FIXTURE_DIRECTORY, "bundled://sample_data/synthetic")

        assert first.idempotent_replay is False
        assert first.import_batch.status == "reconciled"
        assert first.import_batch.accepted_count == 131
        assert first.import_batch.rejected_count == 0
        assert first.import_batch.control_totals["contribution"] == "459000.00"
        assert first.snapshot is not None
        assert first.snapshot.status == "draft"
        assert _count(Order) == 12
        assert _count(OrderLine) == 12
        assert _count(CostRecord) == 48
        assert _count(ReturnRecord) == 3
        assert _count(OrderEvent) == 56

        second = import_directory(FIXTURE_DIRECTORY, "bundled://sample_data/synthetic")
        assert second.idempotent_replay is True
        assert second.import_batch.import_id == first.import_batch.import_id
        assert second.snapshot is not None
        assert second.snapshot.snapshot_id == first.snapshot.snapshot_id
        assert second.import_batch.duplicate_count == 1
        assert _count(ImportBatch) == 1
        assert _count(Snapshot) == 1
        assert _count(Order) == 12


def test_invalid_dataset_is_quarantined_with_row_errors(app):
    files = files_from_directory(FIXTURE_DIRECTORY)
    files["orders.csv"] = files["orders.csv"].replace(b"150000.00", b"150001.00", 1)

    with app.app_context():
        outcome = import_files(files, "test://invalid-fixture")

        assert outcome.snapshot is None
        assert outcome.import_batch.status == "quarantined"
        assert outcome.import_batch.accepted_count == 0
        assert outcome.import_batch.rejected_count >= 1
        assert any(error["code"] == "control_mismatch" for error in outcome.import_batch.row_errors)
        assert _count(Order) == 0


def _login(client, user: dict[str, str]) -> str:
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200
    return response.json["csrf_token"]


def test_api_requires_approval_before_publication(client, provision_user):
    administrator = provision_user("admin@example.test", "administrator")
    finance = provision_user("finance@example.test", "finance")

    admin_csrf = _login(client, administrator)
    imported = client.post("/api/v1/imports/synthetic", headers={"X-CSRF-Token": admin_csrf})
    assert imported.status_code == 201
    import_id = imported.json["import"]["import_id"]
    snapshot_id = imported.json["snapshot"]["snapshot_id"]

    premature = client.post(
        f"/api/v1/snapshots/{snapshot_id}/publish",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert premature.status_code == 409
    assert premature.json["error"]["code"] == "approval_required"

    finance_csrf = _login(client, finance)
    approved = client.post(
        f"/api/v1/snapshots/{snapshot_id}/approve",
        headers={"X-CSRF-Token": finance_csrf},
    )
    assert approved.status_code == 200
    assert approved.json["snapshot"]["status"] == "approved"
    assert approved.json["snapshot"]["approved_by"] == finance["user_id"]

    admin_csrf = _login(client, administrator)
    published = client.post(
        f"/api/v1/snapshots/{snapshot_id}/publish",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert published.status_code == 200
    assert published.json["snapshot"]["status"] == "published"
    assert published.json["snapshot"]["published_at"]

    status = client.get(f"/api/v1/imports/{import_id}")
    assert status.status_code == 200
    assert status.json["import"]["status"] == "published"
    assert status.json["snapshot"]["status"] == "published"

    replay = client.post("/api/v1/imports/synthetic", headers={"X-CSRF-Token": admin_csrf})
    assert replay.status_code == 200
    assert replay.json["idempotent_replay"] is True
    assert replay.json["import"]["import_id"] == import_id
    assert replay.json["snapshot"]["snapshot_id"] == snapshot_id


def test_import_requires_authentication_and_csrf(client, provision_user):
    unauthenticated = client.post("/api/v1/imports/synthetic")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json["error"]["code"] == "authentication_required"

    administrator = provision_user("admin@example.test", "administrator")
    _login(client, administrator)
    missing_csrf = client.post("/api/v1/imports/synthetic")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json["error"]["code"] == "csrf_failed"


def test_cross_tenant_user_cannot_read_import_or_snapshot(client, provision_user):
    administrator = provision_user("admin@example.test", "administrator")
    outsider = provision_user("outsider@example.test", "administrator", tenant_id="other-tenant")
    admin_csrf = _login(client, administrator)
    imported = client.post("/api/v1/imports/synthetic", headers={"X-CSRF-Token": admin_csrf}).json

    _login(client, outsider)
    import_response = client.get(f"/api/v1/imports/{imported['import']['import_id']}")
    snapshot_response = client.get(f"/api/v1/snapshots/{imported['snapshot']['snapshot_id']}")
    assert import_response.status_code == 403
    assert snapshot_response.status_code == 403
    assert import_response.json["error"]["code"] == "forbidden"
    assert snapshot_response.json["error"]["code"] == "forbidden"
