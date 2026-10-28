from __future__ import annotations

import logging
import secrets
import time
from uuid import uuid4

from flask import Flask, g, request

from margina.config import Config
from margina.errors import register_error_handlers
from margina.extensions import db, migrate


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)
    app.config.from_prefixed_env(prefix="MARGINA")
    Config.validate(app.config)

    db.init_app(app)
    from margina import models as _models  # noqa: F401

    migrate.init_app(app, db)

    from margina.api.auth import auth_api
    from margina.api.demo import demo_api
    from margina.api.health import health_api
    from margina.api.imports import imports_api
    from margina.api.metrics import metrics_api
    from margina.api.workspace import workspace_api
    from margina.auth.cli import auth_cli
    from margina.web.routes import web

    app.register_blueprint(web)
    app.register_blueprint(auth_api, url_prefix="/api/v1")
    app.register_blueprint(health_api, url_prefix="/api/v1")
    app.register_blueprint(metrics_api, url_prefix="/api/v1")
    app.register_blueprint(imports_api, url_prefix="/api/v1")
    app.register_blueprint(workspace_api, url_prefix="/api/v1")
    app.register_blueprint(demo_api, url_prefix="/api/v1/demo")
    app.cli.add_command(auth_cli)
    register_error_handlers(app)
    _configure_logging(app)
    _register_request_context(app)
    return app


def _configure_logging(app: Flask) -> None:
    level = getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _register_request_context(app: Flask) -> None:
    @app.before_request
    def start_request() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or str(uuid4())

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.get("request_id", secrets.token_hex(8))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
        if request.path.startswith(("/api/v1/auth", "/api/v1/imports", "/api/v1/snapshots", "/api/v1/organizations")):
            response.headers["Cache-Control"] = "no-store"
        duration_ms = (time.perf_counter() - g.get("request_started_at", time.perf_counter())) * 1000
        app.logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            response.headers["X-Request-ID"],
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response
