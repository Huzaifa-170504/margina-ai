from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from margina.extensions import db
from margina.imports.validation import (
    DatasetIdentity,
    DatasetValidationError,
    ValidatedDataset,
    files_from_directory,
    validate_dataset,
)
from margina.models import (
    AuditEvent,
    CostRecord,
    ImportBatch,
    Order,
    OrderEvent,
    OrderLine,
    Organization,
    ReturnRecord,
    Snapshot,
)

MAPPING_VERSION = "synthetic-csv-v1"
METRIC_VERSION = "1.0.0"


@dataclass(frozen=True)
class ImportOutcome:
    import_batch: ImportBatch
    snapshot: Snapshot | None
    idempotent_replay: bool


class WorkflowError(Exception):
    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def import_directory(directory: Path, object_key: str, actor_id: str = "system") -> ImportOutcome:
    return import_files(files_from_directory(directory), object_key, actor_id)


def import_files(files: dict[str, bytes], object_key: str, actor_id: str = "system") -> ImportOutcome:
    try:
        dataset = validate_dataset(files)
    except DatasetValidationError as error:
        if error.identity is None:
            raise WorkflowError(
                "Dataset identity could not be established; no import batch was created.",
                "invalid_dataset_identity",
                422,
            ) from error
        return _store_quarantined_import(error, object_key, actor_id)

    existing = _find_import(dataset.identity.tenant_id, dataset.dataset_hash)
    if existing is not None:
        existing.duplicate_count += 1
        snapshot = db.session.scalar(select(Snapshot).where(Snapshot.import_id == existing.import_id))
        _audit(dataset.identity.tenant_id, actor_id, "import.replayed", "import", existing.import_id)
        db.session.commit()
        return ImportOutcome(existing, snapshot, True)

    try:
        organization = _ensure_organization(dataset.identity)
        batch = ImportBatch(
            tenant_id=organization.tenant_id,
            source_system=dataset.identity.source_system,
            source_file_hash=dataset.dataset_hash,
            object_key=object_key,
            mapping_version=MAPPING_VERSION,
            status="validating",
            accepted_count=0,
            rejected_count=0,
            duplicate_count=0,
            control_totals={},
            row_errors=[],
        )
        db.session.add(batch)
        db.session.flush()
        snapshot = Snapshot(
            tenant_id=organization.tenant_id,
            import_id=batch.import_id,
            metric_version=METRIC_VERSION,
            status="draft",
            limitations=["Synthetic fixture; no customer outcomes or causal claims."],
        )
        db.session.add(snapshot)
        db.session.flush()
        _persist_dataset(dataset, snapshot.snapshot_id)
        batch.status = "reconciled"
        batch.accepted_count = dataset.accepted_count
        batch.control_totals = dataset.control_totals
        _audit(organization.tenant_id, actor_id, "import.reconciled", "import", batch.import_id)
        db.session.commit()
        return ImportOutcome(batch, snapshot, False)
    except IntegrityError:
        db.session.rollback()
        existing = _find_import(dataset.identity.tenant_id, dataset.dataset_hash)
        if existing is None:
            raise
        existing.duplicate_count += 1
        snapshot = db.session.scalar(select(Snapshot).where(Snapshot.import_id == existing.import_id))
        db.session.commit()
        return ImportOutcome(existing, snapshot, True)
    except Exception:
        db.session.rollback()
        raise


def approve_snapshot(snapshot_id: str, actor_id: str) -> tuple[Snapshot, bool]:
    snapshot = db.session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise WorkflowError("Snapshot was not found.", "snapshot_not_found", 404)
    if snapshot.status in {"approved", "published"}:
        return snapshot, True
    if snapshot.status != "draft":
        raise WorkflowError("Only a draft snapshot can be approved.", "invalid_snapshot_state", 409)
    batch = db.session.get(ImportBatch, snapshot.import_id)
    if batch is None or batch.status != "reconciled" or batch.rejected_count:
        raise WorkflowError("Snapshot import has not passed reconciliation.", "reconciliation_required", 409)

    snapshot.status = "approved"
    snapshot.approved_at = datetime.now(UTC)
    snapshot.approved_by = actor_id
    _audit(snapshot.tenant_id, actor_id, "snapshot.approved", "snapshot", snapshot.snapshot_id)
    db.session.commit()
    return snapshot, False


def publish_snapshot(snapshot_id: str, actor_id: str) -> tuple[Snapshot, bool]:
    snapshot = db.session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise WorkflowError("Snapshot was not found.", "snapshot_not_found", 404)
    if snapshot.status == "published":
        return snapshot, True
    if snapshot.status != "approved":
        raise WorkflowError("Snapshot must be approved before publication.", "approval_required", 409)

    previously_published = db.session.scalars(
        select(Snapshot).where(
            Snapshot.tenant_id == snapshot.tenant_id,
            Snapshot.status == "published",
            Snapshot.snapshot_id != snapshot.snapshot_id,
        )
    ).all()
    for previous in previously_published:
        previous.status = "superseded"

    snapshot.status = "published"
    snapshot.published_at = datetime.now(UTC)
    snapshot.published_by = actor_id
    batch = db.session.get(ImportBatch, snapshot.import_id)
    if batch is None:
        raise WorkflowError("Snapshot import record is missing.", "import_not_found", 409)
    batch.status = "published"
    _audit(snapshot.tenant_id, actor_id, "snapshot.published", "snapshot", snapshot.snapshot_id)
    db.session.commit()
    return snapshot, False


def get_import(import_id: str) -> tuple[ImportBatch, Snapshot | None]:
    batch = db.session.get(ImportBatch, import_id)
    if batch is None:
        raise WorkflowError("Import was not found.", "import_not_found", 404)
    snapshot = db.session.scalar(select(Snapshot).where(Snapshot.import_id == import_id))
    return batch, snapshot


def get_snapshot(snapshot_id: str) -> Snapshot:
    snapshot = db.session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise WorkflowError("Snapshot was not found.", "snapshot_not_found", 404)
    return snapshot


def _store_quarantined_import(
    error: DatasetValidationError,
    object_key: str,
    actor_id: str,
) -> ImportOutcome:
    identity = error.identity
    if identity is None:
        raise AssertionError("Quarantine requires a trusted identity.")
    existing = _find_import(identity.tenant_id, error.dataset_hash)
    if existing is not None:
        existing.duplicate_count += 1
        db.session.commit()
        return ImportOutcome(existing, None, True)

    _ensure_organization(identity)
    batch = ImportBatch(
        tenant_id=identity.tenant_id,
        source_system=identity.source_system,
        source_file_hash=error.dataset_hash,
        object_key=object_key,
        mapping_version=MAPPING_VERSION,
        status="quarantined",
        accepted_count=0,
        rejected_count=len({(item["file"], item["row"]) for item in error.errors}),
        duplicate_count=0,
        control_totals={},
        row_errors=error.errors,
    )
    db.session.add(batch)
    db.session.flush()
    _audit(identity.tenant_id, actor_id, "import.quarantined", "import", batch.import_id)
    db.session.commit()
    return ImportOutcome(batch, None, False)


def _find_import(tenant_id: str, dataset_hash: str) -> ImportBatch | None:
    return db.session.scalar(
        select(ImportBatch).where(
            ImportBatch.tenant_id == tenant_id,
            ImportBatch.source_file_hash == dataset_hash,
        )
    )


def _ensure_organization(identity: DatasetIdentity) -> Organization:
    organization = db.session.get(Organization, identity.tenant_id)
    if organization is None:
        organization = Organization(
            tenant_id=identity.tenant_id,
            name="Synthetic Distributor",
            currency=identity.currency,
            reporting_timezone=identity.reporting_timezone,
            status="setup",
        )
        db.session.add(organization)
        db.session.flush()
    elif organization.currency != identity.currency or organization.reporting_timezone != identity.reporting_timezone:
        raise WorkflowError(
            "Dataset policy conflicts with the existing organization.", "organization_policy_conflict", 409
        )
    return organization


def _persist_dataset(dataset: ValidatedDataset, snapshot_id: str) -> None:
    tenant_id = dataset.identity.tenant_id
    for row in dataset.rows["orders.csv"]:
        db.session.add(
            Order(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                source_system=row["source_system"],
                order_id=row["order_id"],
                customer_id=row["customer_id"],
                branch_id=row["branch_id"],
                currency=row["currency"],
                occurred_at=_datetime(row["occurred_at"]),
                original_timezone=row["original_timezone"],
                source_reference=row["source_reference"],
            )
        )
    db.session.flush()

    for row in dataset.rows["order_lines.csv"]:
        db.session.add(
            OrderLine(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                order_id=row["order_id"],
                line_id=row["line_id"],
                product_id=row["product_id"],
                quantity=Decimal(row["quantity"]),
                unit_price=Decimal(row["unit_price"]),
                discount=Decimal(row["discount"]),
                tax=Decimal(row["tax"]),
                currency=row["currency"],
                source_row_number=int(row["_row_number"]),
            )
        )
    for row in dataset.rows["costs.csv"]:
        db.session.add(
            CostRecord(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                cost_id=row["cost_id"],
                order_id=row["order_id"],
                line_id=row["line_id"] or None,
                category=row["category"],
                amount=Decimal(row["amount"]),
                currency=row["currency"],
                effective_at=_datetime(row["effective_at"]),
                included_in_contribution=row["included_in_contribution"].lower() == "true",
            )
        )
    for row in dataset.rows["returns.csv"]:
        db.session.add(
            ReturnRecord(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                source_system=row["source_system"],
                return_id=row["return_id"],
                order_id=row["order_id"],
                line_id=row["line_id"] or None,
                refunded_revenue=Decimal(row["refunded_revenue"]),
                inventory_recovery_amount=Decimal(row["inventory_recovery_amount"]),
                currency=row["currency"],
                effective_at=_datetime(row["effective_at"]),
                original_timezone=row["original_timezone"],
                source_reference=row["source_reference"],
            )
        )
    for row in dataset.rows["process_events.csv"]:
        db.session.add(
            OrderEvent(
                tenant_id=tenant_id,
                snapshot_id=snapshot_id,
                event_id=row["event_id"],
                order_id=row["order_id"],
                activity=row["activity"],
                lifecycle_marker=row["lifecycle_marker"] or None,
                occurred_at=_datetime(row["occurred_at"]),
                ingested_at=_datetime(row["ingested_at"]),
                original_timezone=row["original_timezone"],
                source_reference=row["source_reference"],
            )
        )
    db.session.flush()


def _audit(tenant_id: str, actor_id: str, action: str, resource_type: str, resource_id: str | None) -> None:
    db.session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details={},
        )
    )


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
