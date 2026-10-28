from __future__ import annotations

import hmac

from flask import request, session
from sqlalchemy import select

from margina.errors import ApiError
from margina.extensions import db
from margina.models import Membership, UserAccount


def require_user() -> UserAccount:
    user_id = session.get("user_id")
    session_version = session.get("session_version")
    if not isinstance(user_id, str) or not isinstance(session_version, int):
        raise ApiError("Authentication is required.", 401, "authentication_required")
    account = db.session.get(UserAccount, user_id)
    if account is None or account.status != "active" or account.session_version != session_version:
        session.clear()
        raise ApiError("Authentication is required.", 401, "authentication_required")
    return account


def require_csrf() -> None:
    require_user()
    expected = session.get("csrf_token")
    provided = request.headers.get("X-CSRF-Token")
    if not isinstance(expected, str) or not isinstance(provided, str) or not hmac.compare_digest(expected, provided):
        raise ApiError("A valid CSRF token is required.", 403, "csrf_failed")


def require_tenant_access(
    tenant_id: str,
    roles: set[str] | frozenset[str] | None = None,
    *,
    require_full_scope: bool = False,
) -> Membership:
    account = require_user()
    membership = db.session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == account.user_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise ApiError("You are not authorized for this organization.", 403, "forbidden")
    if roles is not None and membership.role not in roles:
        raise ApiError("Your role is not authorized for this action.", 403, "forbidden")
    if require_full_scope and membership.branch_scope:
        raise ApiError("This action requires unrestricted branch scope.", 403, "branch_scope_forbidden")
    return membership


def require_branch_access(tenant_id: str, branch_id: str, roles: set[str] | None = None) -> Membership:
    membership = require_tenant_access(tenant_id, roles)
    if membership.branch_scope and branch_id not in membership.branch_scope:
        raise ApiError("You are not authorized for this branch.", 403, "branch_scope_forbidden")
    return membership
