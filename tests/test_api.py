def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_readiness_checks_database(client):
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json["checks"]["database"] == "ok"


def test_demo_page_and_metric_dictionary_are_available(client):
    page = client.get("/demo")
    definitions = client.get("/api/v1/metrics/definitions")
    assert page.status_code == 200
    assert b"Published synthetic demo" in page.data
    assert definitions.status_code == 200
    assert definitions.json["metric_version"] == "1.0.0"


def test_demo_filter_changes_computed_metrics(client, published_snapshot):
    all_branches = client.get("/api/v1/demo/summary").json
    branch_a = client.get("/api/v1/demo/summary?branch=Branch%20A").json
    assert all_branches["metrics"]["net_revenue"] != branch_a["metrics"]["net_revenue"]
    assert branch_a["coverage"]["financial_orders"] == 4
    assert all_branches["snapshot_id"] == published_snapshot
    assert all_branches["metrics"]["net_revenue"] == "2018000.00"
    assert all_branches["metrics"]["contribution"] == "459000.00"


def test_unknown_demo_branch_is_rejected(client, published_snapshot):
    response = client.get("/api/v1/demo/summary?branch=Unknown")
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_filter"


def test_process_map_is_evidence_linked(client, published_snapshot):
    response = client.get("/api/v1/demo/process")
    assert response.status_code == 200
    assert response.json["snapshot_id"]
    assert response.json["case_count"] == 12
    assert response.json["transitions"]


def test_scenario_is_deterministic_and_session_scoped(client, published_snapshot):
    response = client.post(
        "/api/v1/demo/scenarios/shipping",
        json={"shipment_count": 100, "saving_per_shipment": "500", "incremental_cost": "10000"},
    )
    assert response.status_code == 200
    assert response.json["scenario"]["estimated_net_savings"] == "40000.00"
    assert client.post("/api/v1/demo/reset").json == {"reset": True, "scope": "current_demo_session"}


def test_scenario_rejects_non_finite_values(client):
    response = client.post(
        "/api/v1/demo/scenarios/shipping",
        json={"shipment_count": 1, "saving_per_shipment": "NaN", "incremental_cost": 0},
    )
    assert response.status_code == 422
