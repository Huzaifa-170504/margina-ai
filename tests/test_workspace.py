def _login(client, user):
    response = client.post("/api/v1/auth/login", json={"email": user["email"], "password": user["password"]})
    assert response.status_code == 200
    return response.json


def test_login_and_workspace_pages_render(client):
    login = client.get("/login")
    workspace = client.get("/workspace")
    assert login.status_code == 200
    assert b"Sign in to continue" in login.data
    assert workspace.status_code == 200
    assert b"Authenticated workspace" in workspace.data


def test_finance_workspace_reads_published_snapshot(client, provision_user, published_snapshot):
    finance = provision_user("finance@example.test", "finance")
    _login(client, finance)

    summary = client.get("/api/v1/organizations/demo-distributor/dashboard/summary")
    orders = client.get("/api/v1/organizations/demo-distributor/dashboard/orders")
    process = client.get("/api/v1/organizations/demo-distributor/dashboard/process")

    assert summary.status_code == 200
    assert summary.json["snapshot_id"] == published_snapshot
    assert summary.json["metrics"]["contribution"] == "459000.00"
    assert summary.json["coverage"]["financial_orders"] == 12
    assert orders.status_code == 200
    assert len(orders.json["orders"]) == 12
    assert process.status_code == 200
    assert process.json["case_count"] == 12
    assert process.json["sla_breach_count"] == 6
    assert process.json["approval_loop_count"] == 4


def test_branch_scope_is_applied_server_side(client, provision_user, published_snapshot):
    finance = provision_user("branch-finance@example.test", "finance", branch_scope=("Branch A",))
    _login(client, finance)

    summary = client.get("/api/v1/organizations/demo-distributor/dashboard/summary")
    orders = client.get("/api/v1/organizations/demo-distributor/dashboard/orders")
    denied = client.get("/api/v1/organizations/demo-distributor/dashboard/summary?branch=Branch%20B")

    assert summary.status_code == 200
    assert summary.json["available_branches"] == ["Branch A"]
    assert summary.json["coverage"]["financial_orders"] == 4
    assert {order["branch_id"] for order in orders.json["orders"]} == {"Branch A"}
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "branch_scope_forbidden"


def test_operations_role_sees_process_but_not_financials(client, provision_user, published_snapshot):
    operations = provision_user("operations@example.test", "operations")
    _login(client, operations)

    financial = client.get("/api/v1/organizations/demo-distributor/dashboard/summary")
    process = client.get("/api/v1/organizations/demo-distributor/dashboard/process")

    assert financial.status_code == 403
    assert financial.json["error"]["code"] == "forbidden"
    assert process.status_code == 200
    assert process.json["snapshot_id"] == published_snapshot
