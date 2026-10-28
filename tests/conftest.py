from pathlib import Path

import pytest

from margina import create_app
from margina.auth.service import create_organization, create_user_with_membership
from margina.config import Config
from margina.extensions import db
from margina.imports.service import approve_snapshot, import_directory, publish_snapshot
from margina.models import Organization


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def provision_user(app):
    def provision(
        email: str,
        role: str,
        *,
        tenant_id: str = "demo-distributor",
        branch_scope: tuple[str, ...] = (),
        password: str = "correct-horse-battery-staple",
    ):
        with app.app_context():
            if db.session.get(Organization, tenant_id) is None:
                create_organization(tenant_id, "Synthetic Distributor", "PKR", "Asia/Karachi")
            account, membership = create_user_with_membership(email, password, tenant_id, role, branch_scope)
            return {
                "user_id": account.user_id,
                "membership_id": membership.membership_id,
                "email": account.email,
                "password": password,
            }

    return provision


@pytest.fixture()
def published_snapshot(app):
    fixture_directory = Path(app.root_path).parent / "sample_data" / "synthetic"
    with app.app_context():
        outcome = import_directory(fixture_directory, "bundled://sample_data/synthetic")
        assert outcome.snapshot is not None
        snapshot, _ = approve_snapshot(outcome.snapshot.snapshot_id, "test-finance")
        snapshot, _ = publish_snapshot(snapshot.snapshot_id, "test-administrator")
        return snapshot.snapshot_id
