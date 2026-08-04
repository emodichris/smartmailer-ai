"""Small, dependency-free password hashing and signed dashboard sessions."""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import os
import secrets
import sys
import time
from pathlib import Path


PASSWORD_ITERATIONS = 600_000
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256:{}:{}:{}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_value, expected_value = encoded.split(":", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode())
        expected = base64.urlsafe_b64decode(expected_value.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def create_session(username: str, secret: str, issued_at: int | None = None) -> str:
    payload = f"{username}:{issued_at if issued_at is not None else int(time.time())}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def verify_session(
    token: str,
    username: str,
    secret: str,
    max_age_seconds: int = 28_800,
    now: int | None = None,
) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        token_username, issued_at_value, signature = decoded.rsplit(":", 2)
        issued_at = int(issued_at_value)
        current_time = now if now is not None else int(time.time())
        payload = f"{token_username}:{issued_at}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return (
            hmac.compare_digest(signature, expected)
            and hmac.compare_digest(token_username, username)
            and 0 <= current_time - issued_at <= max_age_seconds
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return False


def main() -> None:
    if len(sys.argv) not in {2, 3} or sys.argv[1] not in {"hash-password", "configure-env"}:
        raise SystemExit(
            "Usage: python -m services.dashboard_auth hash-password | configure-env [env-file]"
        )
    password = getpass.getpass("New dashboard password: ")
    confirmation = getpass.getpass("Confirm dashboard password: ")
    if not password or password != confirmation:
        raise SystemExit("Passwords were empty or did not match.")
    encoded = hash_password(password)
    if sys.argv[1] == "hash-password":
        print(encoded)
        return

    env_path = Path(sys.argv[2] if len(sys.argv) == 3 else ".env")
    if not env_path.is_file():
        raise SystemExit(f"Environment file was not found: {env_path}")
    settings = {
        "DASHBOARD_APP_PASSWORD_HASH": encoded,
        "DASHBOARD_SESSION_SECRET": secrets.token_urlsafe(48),
    }
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    found = set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in settings:
            updated_lines.append(f"{key}={settings[key]}")
            found.add(key)
        else:
            updated_lines.append(line)
    if found != set(settings):
        updated_lines.append("")
        updated_lines.extend(f"{key}={value}" for key, value in settings.items() if key not in found)
    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    print("Dashboard login configured successfully.")


if __name__ == "__main__":
    main()
