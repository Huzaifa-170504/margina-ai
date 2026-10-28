from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, ClassVar


class Config:
    APP_ENV = os.getenv("APP_ENV", "development").lower()
    SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///margina.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict[str, bool]] = {"pool_pre_ping": True}
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    REPORTING_TIMEZONE = os.getenv("REPORTING_TIMEZONE", "Asia/Karachi")
    DEMO_ENABLED = os.getenv("DEMO_ENABLED", "true").lower() in {"1", "true", "yes"}
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    JSON_SORT_KEYS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(APP_ENV == "production")).lower() in {
        "1",
        "true",
        "yes",
    }
    SESSION_COOKIE_NAME = "margina_session"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv("SESSION_HOURS", "8")))
    SESSION_REFRESH_EACH_REQUEST = False
    MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
    AUTH_LOCK_MINUTES = int(os.getenv("AUTH_LOCK_MINUTES", "15"))
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "12"))

    @staticmethod
    def validate(config: Mapping[str, Any]) -> None:
        if config.get("APP_ENV") == "production":
            if config.get("SECRET_KEY") == "development-only-change-me":
                raise RuntimeError("SECRET_KEY must be set outside development")
            database_url = str(config.get("SQLALCHEMY_DATABASE_URI", ""))
            if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise RuntimeError("Production DATABASE_URL must use PostgreSQL")
            if not config.get("SESSION_COOKIE_SECURE"):
                raise RuntimeError("SESSION_COOKIE_SECURE must be enabled in production")
