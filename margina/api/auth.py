from __future__ import annotations

import secrets

from flask import Blueprint, jsonify, request, session

from margina.auth.context import require_csrf, require_tenant_access, require_user
from margina.auth.service import (
    AuthServiceError,
    assign_membership,
    authenticate,
    list_memberships,
    memberships_for_user,
    update_membership,
)
from margina.errors import ApiError
from margina.extensions import db
from margina.models import Membership, Organization, UserAccount

auth_api = Blueprint("auth_api", __name__)


@auth_api.post("/auth/login")
def login():
    body = _json_object()
    account = _auth_call(authenticate, body.get("email"), body.get("password"))
    session.clear()
    session.permanent = True
    session["user_id"] = account.user_id
    session["session_version"] = account.session_version
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify(_session_payload(account))


@auth_api.post("/auth/logout")
def logout():
    require_csrf()
    session.clear()
    return jsonify({"logged_out": True})


@auth_api.get("/auth/me")
def me():
    return jsonify(_session_payload(require_user()))


@auth_api.get("/organizations/<tenant_id>/memberships")
def memberships_list(tenant_id: str):
    require_tenant_access(tenant_id, {"administrator"}, require_full_scope=True)
    return jsonify(
        {
            "tenant_id": tenant_id,
            "memberships": [
                _membership_payload(membership, account)
                for membership, account in _auth_call(list_memberships, tenant_id)
            ],
        }
    )


@auth_api.post("/organizations/<tenant_id>/memberships")
def membership_create(tenant_id: str):
    require_csrf()
    actor = require_user()
    require_tenant_access(tenant_id, {"administrator"}, require_full_scope=True)
    body = _json_object()
    membership = _auth_call(
        assign_membership,
        tenant_id,
        body.get("user_id"),
        body.get("role"),
        body.get("branch_scope", []),
        actor.user_id,
    )
    account = db.session.get(UserAccount, membership.user_id)
    return jsonify({"membership": _membership_payload(membership, account)}), 201


@auth_api.patch("/organizations/<tenant_id>/memberships/<membership_id>")
def membership_update(tenant_id: str, membership_id: str):
    require_csrf()
    actor = require_user()
    require_tenant_access(tenant_id, {"administrator"}, require_full_scope=True)
    body = _json_object()
    membership = _auth_call(update_membership, tenant_id, membership_id, body, actor.user_id)
    account = db.session.get(UserAccount, membership.user_id)
    return jsonify({"membership": _membership_payload(membership, account)})


def _session_payload(account: UserAccount) -> dict[str, object]:
    return {
        "user": {"user_id": account.user_id, "email": account.email},
        "memberships": [
            _session_membership_payload(membership) for membership in memberships_for_user(account.user_id)
        ],
        "csrf_token": session.get("csrf_token"),
    }


def _session_membership_payload(membership: Membership) -> dict[str, object]:
    payload = _membership_payload(membership)
    organization = db.session.get(Organization, membership.tenant_id)
    payload["organization_name"] = membership.tenant_id if organization is None else organization.name
    return payload


def _membership_payload(membership: Membership, account: UserAccount | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "membership_id": membership.membership_id,
        "tenant_id": membership.tenant_id,
        "user_id": membership.user_id,
        "role": membership.role,
        "branch_scope": membership.branch_scope,
        "status": membership.status,
    }
    if account is not None:
        payload["email"] = account.email
    return payload


def _auth_call(function, *args):
    try:
        return function(*args)
    except AuthServiceError as error:
        raise ApiError(error.message, error.status_code, error.code) from error


def _json_object() -> dict[str, object]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("A JSON object is required.", 422, "validation_error")
    return body
