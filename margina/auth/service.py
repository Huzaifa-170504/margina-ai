from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from sqlalchemy import func, select

from margina.auth.security import (
    consume_dummy_password_check,
    hash_password,
    normalize_email,
    validate_password,
    verify_password,
)
from margina.extensions import db
from margina.models import AuditEvent, Membership, Organization, UserAccount

ROLES = frozenset({"finance", "operations", "analyst", "administrator"})
MEMBERSHIP_STATUSES = frozenset({"invited", "active", "disabled"})


class AuthServiceError(Exception):
    def __init__(self, message: str, code: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def authenticate(email_value: object, password_value: object) -> UserAccount:
    if not isinstance(email_value, str) or not isinstance(password_value, str):
        consume_dummy_password_check("")
        raise _invalid_credentials()
    if len(password_value) > 128:
        consume_dummy_password_check("")
        raise _invalid_credentials()
    try:
        email = normalize_email(email_value)
    except ValueError:
        consume_dummy_password_check(password_value)
        raise _invalid_credentials() from None

    account = db.session.scalar(select(UserAccount).where(UserAccount.email == email))
    if account is None:
        consume_dummy_password_check(password_value)
        current_app.logger.warning("authentication_failed user_id=unknown")
        raise _invalid_credentials()

    now = datetime.now(UTC)
    password_matches = verify_password(account.password_hash, password_value)
    if account.status != "active" or _is_locked(account, now) or not password_matches:
        if account.status == "active" and not _is_locked(account, now):
            account.failed_login_count += 1
            if account.failed_login_count >= current_app.config["MAX_LOGIN_ATTEMPTS"]:
                account.locked_until = now + timedelta(minutes=current_app.config["AUTH_LOCK_MINUTES"])
                account.failed_login_count = 0
            db.session.commit()
        current_app.logger.warning("authentication_failed user_id=%s", account.user_id)
        raise _invalid_credentials()

    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = now
    db.session.commit()
    return account


def create_organization(
    tenant_id: str,
    name: str,
    currency: str,
    reporting_timezone: str,
) -> Organization:
    tenant_id = tenant_id.strip()
    name = name.strip()
    currency = currency.strip().upper()
    if not tenant_id or len(tenant_id) > 36:
        raise AuthServiceError("tenant_id must contain 1-36 characters.", "validation_error", 422)
    if not name or len(name) > 200:
        raise AuthServiceError("Organization name must contain 1-200 characters.", "validation_error", 422)
    if len(currency) != 3 or not currency.isalpha():
        raise AuthServiceError("Currency must be a three-letter code.", "validation_error", 422)
    try:
        ZoneInfo(reporting_timezone)
    except ZoneInfoNotFoundError as error:
        raise AuthServiceError("Unknown IANA reporting timezone.", "validation_error", 422) from error
    if db.session.get(Organization, tenant_id) is not None:
        raise AuthServiceError("Organization already exists.", "organization_exists", 409)
    organization = Organization(
        tenant_id=tenant_id,
        name=name,
        currency=currency,
        reporting_timezone=reporting_timezone,
        status="setup",
    )
    db.session.add(organization)
    db.session.commit()
    return organization


def create_user_with_membership(
    email: str,
    password: str,
    tenant_id: str,
    role: str,
    branch_scope: list[str] | tuple[str, ...],
) -> tuple[UserAccount, Membership]:
    try:
        normalized_email = normalize_email(email)
        validate_password(password, current_app.config["PASSWORD_MIN_LENGTH"])
    except ValueError as error:
        raise AuthServiceError(str(error), "validation_error", 422) from error
    if db.session.scalar(select(UserAccount).where(UserAccount.email == normalized_email)) is not None:
        raise AuthServiceError("User account already exists.", "user_exists", 409)
    _require_organization(tenant_id)
    role = _validate_role(role)
    branches = _validate_branch_scope(branch_scope)

    account = UserAccount(email=normalized_email, password_hash=hash_password(password), status="active")
    db.session.add(account)
    db.session.flush()
    membership = Membership(
        tenant_id=tenant_id,
        user_id=account.user_id,
        role=role,
        branch_scope=branches,
        status="active",
    )
    db.session.add(membership)
    db.session.commit()
    return account, membership


def assign_membership(
    tenant_id: str,
    user_id: str,
    role: str,
    branch_scope: object,
    actor_id: str,
) -> Membership:
    _require_organization(tenant_id)
    if not isinstance(user_id, str):
        raise AuthServiceError("user_id is required.", "validation_error", 422)
    account = db.session.get(UserAccount, user_id)
    if account is None or account.status != "active":
        raise AuthServiceError("Active user account was not found.", "user_not_found", 404)
    existing = db.session.scalar(
        select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
    )
    if existing is not None:
        raise AuthServiceError("Membership already exists.", "membership_exists", 409)
    membership = Membership(
        tenant_id=tenant_id,
        user_id=user_id,
        role=_validate_role(role),
        branch_scope=_validate_branch_scope(branch_scope),
        status="active",
    )
    db.session.add(membership)
    db.session.flush()
    _audit_membership(tenant_id, actor_id, "membership.created", membership)
    db.session.commit()
    return membership


def update_membership(
    tenant_id: str,
    membership_id: str,
    changes: dict[str, object],
    actor_id: str,
) -> Membership:
    membership = db.session.get(Membership, membership_id)
    if membership is None or membership.tenant_id != tenant_id:
        raise AuthServiceError("Membership was not found.", "membership_not_found", 404)
    allowed = {"role", "branch_scope", "status"}
    if not changes or set(changes) - allowed:
        raise AuthServiceError("Only role, branch_scope, and status may be updated.", "validation_error", 422)

    next_role = _validate_role(changes.get("role", membership.role))
    next_status = _validate_status(changes.get("status", membership.status))
    next_scope = _validate_branch_scope(changes.get("branch_scope", membership.branch_scope))
    removing_full_admin = (
        membership.role == "administrator"
        and membership.status == "active"
        and not membership.branch_scope
        and (next_role != "administrator" or next_status != "active" or bool(next_scope))
    )
    if removing_full_admin and _active_full_admin_count(tenant_id) <= 1:
        raise AuthServiceError(
            "The last unrestricted active administrator cannot be removed, restricted, or disabled.",
            "last_administrator_required",
            409,
        )

    membership.role = next_role
    membership.status = next_status
    membership.branch_scope = next_scope
    _audit_membership(tenant_id, actor_id, "membership.updated", membership)
    db.session.commit()
    return membership


def list_memberships(tenant_id: str) -> list[tuple[Membership, UserAccount]]:
    return list(
        db.session.execute(
            select(Membership, UserAccount)
            .join(UserAccount, UserAccount.user_id == Membership.user_id)
            .where(Membership.tenant_id == tenant_id)
            .order_by(UserAccount.email)
        ).all()
    )


def memberships_for_user(user_id: str) -> list[Membership]:
    return list(
        db.session.scalars(select(Membership).where(Membership.user_id == user_id, Membership.status == "active")).all()
    )


def _is_locked(account: UserAccount, now: datetime) -> bool:
    if account.locked_until is None:
        return False
    locked_until = account.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > now


def _invalid_credentials() -> AuthServiceError:
    return AuthServiceError("Invalid email or password.", "invalid_credentials", 401)


def _require_organization(tenant_id: str) -> Organization:
    organization = db.session.get(Organization, tenant_id)
    if organization is None:
        raise AuthServiceError("Organization was not found.", "organization_not_found", 404)
    return organization


def _validate_role(value: object) -> str:
    if not isinstance(value, str) or value not in ROLES:
        raise AuthServiceError("Invalid membership role.", "validation_error", 422)
    return value


def _validate_status(value: object) -> str:
    if not isinstance(value, str) or value not in MEMBERSHIP_STATUSES:
        raise AuthServiceError("Invalid membership status.", "validation_error", 422)
    return value


def _validate_branch_scope(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > 100:
        raise AuthServiceError("branch_scope must be a list of at most 100 branches.", "validation_error", 422)
    branches: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 160:
            raise AuthServiceError("Each branch identifier must contain 1-160 characters.", "validation_error", 422)
        branch = item.strip()
        if branch not in branches:
            branches.append(branch)
    return branches


def _active_full_admin_count(tenant_id: str) -> int:
    return (
        db.session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == "administrator",
                Membership.status == "active",
                Membership.branch_scope == [],
            )
        )
        or 0
    )


def _audit_membership(tenant_id: str, actor_id: str, action: str, membership: Membership) -> None:
    db.session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action=action,
            resource_type="membership",
            resource_id=membership.membership_id,
            details={"role": membership.role, "branch_scope": membership.branch_scope, "status": membership.status},
        )
    )
