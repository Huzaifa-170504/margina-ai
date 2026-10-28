from datetime import UTC, datetime

from margina.extensions import db
from margina.models import UserAccount


def _login(client, email: str, password: str = "correct-horse-battery-staple"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_login_session_and_logout(client, provision_user):
    user = provision_user("Admin@Example.Test", "administrator")

    login = _login(client, "admin@example.test")
    assert login.status_code == 200
    assert login.json["user"]["email"] == "admin@example.test"
    assert login.json["csrf_token"]
    assert login.json["memberships"][0]["role"] == "administrator"

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json["user"]["user_id"] == user["user_id"]
    assert me.headers["Cache-Control"] == "no-store"

    logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login.json["csrf_token"]})
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_failures_are_generic_and_lock_account(client, app, provision_user):
    user = provision_user("finance@example.test", "finance")
    unknown = _login(client, "unknown@example.test", "wrong-password-value")
    assert unknown.status_code == 401
    assert unknown.json["error"]["message"] == "Invalid email or password."

    for _ in range(5):
        response = _login(client, user["email"], "wrong-password-value")
        assert response.status_code == 401
        assert response.json["error"]["message"] == "Invalid email or password."
    assert _login(client, user["email"]).status_code == 401

    with app.app_context():
        account = db.session.get(UserAccount, user["user_id"])
        assert account is not None
        assert account.locked_until is not None
        locked_until = account.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        assert locked_until > datetime.now(UTC)


def test_role_and_branch_scope_protect_imports(client, provision_user):
    finance = provision_user("finance@example.test", "finance")
    finance_login = _login(client, finance["email"])
    denied_role = client.post(
        "/api/v1/imports/synthetic",
        headers={"X-CSRF-Token": finance_login.json["csrf_token"]},
    )
    assert denied_role.status_code == 403
    assert denied_role.json["error"]["code"] == "forbidden"

    restricted_admin = provision_user(
        "restricted-admin@example.test",
        "administrator",
        branch_scope=("Branch A",),
    )
    restricted_login = _login(client, restricted_admin["email"])
    denied_scope = client.post(
        "/api/v1/imports/synthetic",
        headers={"X-CSRF-Token": restricted_login.json["csrf_token"]},
    )
    assert denied_scope.status_code == 403
    assert denied_scope.json["error"]["code"] == "branch_scope_forbidden"


def test_administrator_manages_memberships_and_cannot_remove_last_admin(client, provision_user):
    administrator = provision_user("admin@example.test", "administrator")
    finance = provision_user("finance@example.test", "finance")
    external_analyst = provision_user("analyst@example.test", "analyst", tenant_id="other-tenant")
    login = _login(client, administrator["email"])
    headers = {"X-CSRF-Token": login.json["csrf_token"]}

    listing = client.get("/api/v1/organizations/demo-distributor/memberships")
    assert listing.status_code == 200
    assert {item["email"] for item in listing.json["memberships"]} == {
        "admin@example.test",
        "finance@example.test",
    }

    assigned = client.post(
        "/api/v1/organizations/demo-distributor/memberships",
        json={"user_id": external_analyst["user_id"], "role": "analyst", "branch_scope": ["Branch B"]},
        headers=headers,
    )
    assert assigned.status_code == 201
    assert assigned.json["membership"]["role"] == "analyst"
    assert assigned.json["membership"]["branch_scope"] == ["Branch B"]

    updated = client.patch(
        f"/api/v1/organizations/demo-distributor/memberships/{finance['membership_id']}",
        json={"branch_scope": ["Branch A"]},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json["membership"]["branch_scope"] == ["Branch A"]

    last_admin = client.patch(
        f"/api/v1/organizations/demo-distributor/memberships/{administrator['membership_id']}",
        json={"status": "disabled"},
        headers=headers,
    )
    assert last_admin.status_code == 409
    assert last_admin.json["error"]["code"] == "last_administrator_required"

    restricted_last_admin = client.patch(
        f"/api/v1/organizations/demo-distributor/memberships/{administrator['membership_id']}",
        json={"branch_scope": ["Branch A"]},
        headers=headers,
    )
    assert restricted_last_admin.status_code == 409
    assert restricted_last_admin.json["error"]["code"] == "last_administrator_required"
