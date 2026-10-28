from __future__ import annotations

import re

from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password", method="scrypt")


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise ValueError("A valid email address is required.")
    return email


def validate_password(value: str, minimum_length: int) -> None:
    if len(value) < minimum_length:
        raise ValueError(f"Password must be at least {minimum_length} characters.")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters.")


def hash_password(value: str) -> str:
    return generate_password_hash(value, method="scrypt")


def verify_password(password_hash: str, value: str) -> bool:
    return check_password_hash(password_hash, value)


def consume_dummy_password_check(value: str) -> None:
    check_password_hash(DUMMY_PASSWORD_HASH, value)
