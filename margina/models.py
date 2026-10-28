from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from margina.extensions import db


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class Organization(TimestampMixin, db.Model):
    __tablename__ = "organizations"

    tenant_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reporting_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="setup", nullable=False)

    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="ck_organizations_currency_length"),
        CheckConstraint("status in ('setup', 'active', 'suspended')", name="ck_organizations_status"),
    )


class UserAccount(TimestampMixin, db.Model):
    __tablename__ = "user_accounts"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_version: Mapped[int] = mapped_column(default=1, nullable=False)

    __table_args__ = (
        CheckConstraint("status in ('active', 'disabled')", name="ck_user_accounts_status"),
        CheckConstraint("failed_login_count >= 0", name="ck_user_accounts_failed_login_nonnegative"),
        CheckConstraint("session_version > 0", name="ck_user_accounts_session_version_positive"),
    )


class Membership(TimestampMixin, db.Model):
    __tablename__ = "memberships"

    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    branch_scope: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["organizations.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.user_id"],
            name="fk_memberships_user_account",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        CheckConstraint("role in ('finance', 'operations', 'analyst', 'administrator')", name="ck_memberships_role"),
        CheckConstraint("status in ('invited', 'active', 'disabled')", name="ck_memberships_status"),
        Index("ix_memberships_tenant_status", "tenant_id", "status"),
    )


class ImportBatch(TimestampMixin, db.Model):
    __tablename__ = "import_batches"

    import_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    accepted_count: Mapped[int] = mapped_column(default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(default=0, nullable=False)
    control_totals: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    row_errors: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["organizations.tenant_id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "source_file_hash", name="uq_import_batches_tenant_hash"),
        CheckConstraint(
            "status in ('uploaded', 'validating', 'quarantined', 'reconciled', 'published', 'failed')",
            name="ck_import_batches_status",
        ),
    )


class Snapshot(TimestampMixin, db.Model):
    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    import_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["organizations.tenant_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["import_id"], ["import_batches.import_id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "snapshot_id", name="uq_snapshots_tenant_snapshot"),
        CheckConstraint("status in ('draft', 'approved', 'published', 'superseded')", name="ck_snapshots_status"),
        Index("ix_snapshots_tenant_status", "tenant_id", "status"),
    )


class Order(TimestampMixin, db.Model):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(160))
    branch_id: Mapped[str] = mapped_column(String(160), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_timezone: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"], ["snapshots.tenant_id", "snapshots.snapshot_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "snapshot_id", "source_system", "order_id", name="uq_orders_source_key"),
        UniqueConstraint("tenant_id", "snapshot_id", "order_id", name="uq_orders_tenant_snapshot_order"),
        Index("ix_orders_tenant_snapshot_branch", "tenant_id", "snapshot_id", "branch_id"),
    )


class OrderLine(TimestampMixin, db.Model):
    __tablename__ = "order_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    line_id: Mapped[str] = mapped_column(String(160), nullable=False)
    product_id: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_row_number: Mapped[int | None]

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id", "order_id"],
            ["orders.tenant_id", "orders.snapshot_id", "orders.order_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "snapshot_id", "order_id", "line_id", name="uq_order_lines_business_key"),
        CheckConstraint("quantity >= 0", name="ck_order_lines_quantity_nonnegative"),
    )


class CostRecord(TimestampMixin, db.Model):
    __tablename__ = "cost_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cost_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    included_in_contribution: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id", "order_id"],
            ["orders.tenant_id", "orders.snapshot_id", "orders.order_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "snapshot_id", "cost_id", name="uq_cost_records_business_key"),
    )


class ReturnRecord(TimestampMixin, db.Model):
    __tablename__ = "return_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    return_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(160))
    refunded_revenue: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    inventory_recovery_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_timezone: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id", "order_id"],
            ["orders.tenant_id", "orders.snapshot_id", "orders.order_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "snapshot_id", "return_id", name="uq_return_records_business_key"),
        CheckConstraint("refunded_revenue >= 0", name="ck_return_records_refund_nonnegative"),
        CheckConstraint("inventory_recovery_amount >= 0", name="ck_return_records_recovery_nonnegative"),
    )


class OrderEvent(TimestampMixin, db.Model):
    __tablename__ = "process_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    order_id: Mapped[str] = mapped_column(String(160), nullable=False)
    activity: Mapped[str] = mapped_column(String(160), nullable=False)
    lifecycle_marker: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    original_timezone: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id", "order_id"],
            ["orders.tenant_id", "orders.snapshot_id", "orders.order_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "snapshot_id", "event_id", name="uq_process_events_business_key"),
        Index("ix_process_events_case_time", "tenant_id", "snapshot_id", "order_id", "occurred_at"),
    )


class Investigation(TimestampMixin, db.Model):
    __tablename__ = "investigations"

    finding_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    evidence_references: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    metric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"], ["snapshots.tenant_id", "snapshots.snapshot_id"], ondelete="RESTRICT"
        ),
        CheckConstraint(
            "status in ('open', 'in_review', 'accepted', 'rejected', 'closed')", name="ck_investigations_status"
        ),
    )


class Scenario(TimestampMixin, db.Model):
    __tablename__ = "scenarios"

    scenario_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    assumptions: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"], ["snapshots.tenant_id", "snapshots.snapshot_id"], ondelete="RESTRICT"
        ),
        UniqueConstraint("tenant_id", "scenario_id", "version", name="uq_scenarios_version"),
        CheckConstraint("version > 0", name="ck_scenarios_positive_version"),
    )


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(160))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["organizations.tenant_id"], ondelete="RESTRICT"),
        Index("ix_audit_events_tenant_time", "tenant_id", "occurred_at"),
    )
