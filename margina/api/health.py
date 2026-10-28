from flask import Blueprint, current_app, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from margina.extensions import db

health_api = Blueprint("health_api", __name__)


@health_api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "margina-api"})


@health_api.get("/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        current_app.logger.exception("readiness_database_failed")
        return jsonify({"status": "not_ready", "checks": {"database": "failed"}}), 503
    return jsonify({"status": "ready", "checks": {"database": "ok"}})
