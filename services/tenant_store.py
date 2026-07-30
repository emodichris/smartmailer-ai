"""Minimal tenant isolation and encrypted provider-credential storage."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


DATABASE_PATH = Path(__file__).resolve().parent.parent / "database" / "smartmailer.sqlite3"


class TenantStoreError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _cipher() -> Fernet:
    key = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise TenantStoreError(
            "CREDENTIAL_ENCRYPTION_KEY is not configured. Generate a Fernet key before saving provider credentials."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise TenantStoreError("CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key.") from exc


class TenantStore:
    def __init__(self, database_path: Path = DATABASE_PATH):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY,
                    id TEXT,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS provider_connections (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    credentials_encrypted BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, name)
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    name TEXT NOT NULL,
                    connection_name TEXT NOT NULL,
                    campaign_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    html_template TEXT NOT NULL,
                    text_template TEXT,
                    contacts_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contacts (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    email TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, email)
                );
                CREATE TABLE IF NOT EXISTS workspace_settings (
                    tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
                    signature_html TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # `id` was added after the first local workspaces were created.
            # Keep the original key hash private and give old rows a safe ID too.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(api_keys)")}
            if "id" not in columns:
                conn.execute("ALTER TABLE api_keys ADD COLUMN id TEXT")
            old_rows = conn.execute("SELECT key_hash FROM api_keys WHERE id IS NULL").fetchall()
            for row in old_rows:
                conn.execute(
                    "UPDATE api_keys SET id = ? WHERE key_hash = ?",
                    (f"key_{secrets.token_urlsafe(12)}", row["key_hash"]),
                )

    def create_tenant(self, name: str, key_label: str = "default") -> tuple[dict, str]:
        normalized_name = name.strip()
        if not normalized_name:
            raise TenantStoreError("Tenant name is required.")

        tenant_id = f"tenant_{secrets.token_urlsafe(12)}"
        api_key = self._new_api_key()
        key_id = self._new_key_id()
        now = _utc_now()
        key_label = self._validate_key_label(key_label)
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (tenant_id, normalized_name, now),
            )
            conn.execute(
                "INSERT INTO api_keys (key_hash, id, tenant_id, label, created_at) VALUES (?, ?, ?, ?, ?)",
                (_api_key_hash(api_key), key_id, tenant_id, key_label, now),
            )
        return {"id": tenant_id, "name": normalized_name, "created_at": now}, api_key

    @staticmethod
    def _new_api_key() -> str:
        return f"sm_live_{secrets.token_urlsafe(32)}"

    @staticmethod
    def _new_key_id() -> str:
        return f"key_{secrets.token_urlsafe(12)}"

    @staticmethod
    def _validate_key_label(label: str) -> str:
        normalized = label.strip() or "default"
        if not re.fullmatch(r"[A-Za-z0-9 _-]{1,60}", normalized):
            raise TenantStoreError(
                "API-key labels may contain only letters, numbers, spaces, _ and -. Never enter a provider secret here."
            )
        return normalized

    def rotate_api_key(self, tenant_id: str, current_api_key: str, label: str = "rotated") -> str:
        new_api_key = self._new_api_key()
        now = _utc_now()
        label = self._validate_key_label(label)
        with self.connection() as conn:
            result = conn.execute(
                """
                UPDATE api_keys SET revoked_at = ?
                WHERE tenant_id = ? AND key_hash = ? AND revoked_at IS NULL
                """,
                (now, tenant_id, _api_key_hash(current_api_key)),
            )
            if result.rowcount != 1:
                raise TenantStoreError("The API key could not be rotated.")
            conn.execute(
                "INSERT INTO api_keys (key_hash, id, tenant_id, label, created_at) VALUES (?, ?, ?, ?, ?)",
                (_api_key_hash(new_api_key), self._new_key_id(), tenant_id, label, now),
            )
        return new_api_key

    def create_api_key(self, tenant_id: str, label: str) -> tuple[dict, str]:
        """Create an additional device token. The plaintext token is never stored."""
        api_key = self._new_api_key()
        key_id = self._new_key_id()
        now = _utc_now()
        label = self._validate_key_label(label)
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, id, tenant_id, label, created_at) VALUES (?, ?, ?, ?, ?)",
                (_api_key_hash(api_key), key_id, tenant_id, label, now),
            )
        return {"id": key_id, "label": label, "created_at": now}, api_key

    def list_api_keys(self, tenant_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, label, created_at, revoked_at
                FROM api_keys WHERE tenant_id = ?
                ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_api_key(self, tenant_id: str, key_id: str) -> None:
        with self.connection() as conn:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM api_keys WHERE tenant_id = ? AND revoked_at IS NULL",
                (tenant_id,),
            ).fetchone()[0]
            if active_count <= 1:
                raise TenantStoreError("Create another API key before revoking the last active key.")
            result = conn.execute(
                """
                UPDATE api_keys SET revoked_at = ?
                WHERE tenant_id = ? AND id = ? AND revoked_at IS NULL
                """,
                (_utc_now(), tenant_id, key_id),
            )
            if result.rowcount != 1:
                raise TenantStoreError("API key was not found or has already been revoked.")

    def tenant_for_api_key(self, api_key: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT tenants.id, tenants.name, tenants.created_at
                FROM api_keys JOIN tenants ON tenants.id = api_keys.tenant_id
                WHERE api_keys.key_hash = ? AND api_keys.revoked_at IS NULL
                """,
                (_api_key_hash(api_key),),
            ).fetchone()
        return dict(row) if row else None

    def save_provider_connection(
        self, tenant_id: str, name: str, provider: str, credentials: dict
    ) -> dict:
        connection_name = name.strip().lower()
        if not connection_name.replace("-", "").replace("_", "").isalnum():
            raise TenantStoreError("Connection names may contain letters, numbers, - and _ only.")

        encrypted = _cipher().encrypt(json.dumps(credentials).encode("utf-8"))
        connection_id = f"connection_{secrets.token_urlsafe(12)}"
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO provider_connections
                    (id, tenant_id, name, provider, credentials_encrypted, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, name) DO UPDATE SET
                    provider = excluded.provider,
                    credentials_encrypted = excluded.credentials_encrypted,
                    updated_at = excluded.updated_at
                """,
                (connection_id, tenant_id, connection_name, provider, encrypted, now, now),
            )
        return {"name": connection_name, "provider": provider, "updated_at": now}

    def get_provider_connection(self, tenant_id: str, name: str) -> tuple[str, dict]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT provider, credentials_encrypted FROM provider_connections
                WHERE tenant_id = ? AND name = ?
                """,
                (tenant_id, name.strip().lower()),
            ).fetchone()
        if not row:
            raise TenantStoreError("Provider connection was not found for this workspace.")
        try:
            credentials = json.loads(_cipher().decrypt(row["credentials_encrypted"]).decode("utf-8"))
        except InvalidToken as exc:
            raise TenantStoreError("Unable to decrypt provider credentials.") from exc
        return row["provider"], credentials

    def list_provider_connections(self, tenant_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT name, provider, created_at, updated_at FROM provider_connections
                WHERE tenant_id = ? ORDER BY name
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_campaign(self, tenant_id: str, campaign: dict) -> dict:
        campaign_id = f"campaign_{secrets.token_urlsafe(12)}"
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO campaigns (
                    id, tenant_id, name, connection_name, campaign_type, subject,
                    html_template, text_template, contacts_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign_id,
                    tenant_id,
                    campaign["name"],
                    campaign["connection_name"].strip().lower(),
                    campaign["campaign_type"],
                    campaign["subject"],
                    campaign["html_template"],
                    campaign.get("text_template"),
                    json.dumps(campaign["contacts"]),
                    "draft",
                    now,
                    now,
                ),
            )
        return self.get_campaign(tenant_id, campaign_id)

    def get_campaign(self, tenant_id: str, campaign_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?",
                (campaign_id, tenant_id),
            ).fetchone()
        if not row:
            raise TenantStoreError("Campaign was not found for this workspace.")
        campaign = dict(row)
        campaign["contacts"] = json.loads(campaign.pop("contacts_json"))
        return campaign

    def update_campaign(self, tenant_id: str, campaign_id: str, changes: dict) -> dict:
        current = self.get_campaign(tenant_id, campaign_id)
        if current["status"] != "draft":
            raise TenantStoreError("Only unsent campaign drafts can be edited.")
        allowed = {
            "name", "connection_name", "campaign_type", "subject",
            "html_template", "text_template", "contacts",
        }
        updates = {key: value for key, value in changes.items() if key in allowed and value is not None}
        if not updates:
            return current
        if "contacts" in updates:
            updates["contacts_json"] = json.dumps(updates.pop("contacts"))
        if "connection_name" in updates:
            updates["connection_name"] = updates["connection_name"].strip().lower()
        updates["updated_at"] = _utc_now()
        assignments = ", ".join(f"{column} = ?" for column in updates)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE campaigns SET {assignments} WHERE id = ? AND tenant_id = ?",
                (*updates.values(), campaign_id, tenant_id),
            )
        return self.get_campaign(tenant_id, campaign_id)

    def list_campaigns(self, tenant_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, connection_name, campaign_type, subject, status, created_at, updated_at
                FROM campaigns WHERE tenant_id = ? ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_campaign(self, tenant_id: str, campaign_id: str) -> None:
        with self.connection() as conn:
            result = conn.execute(
                "DELETE FROM campaigns WHERE id = ? AND tenant_id = ? AND status = ?",
                (campaign_id, tenant_id, "draft"),
            )
        if result.rowcount != 1:
            raise TenantStoreError("Campaign was not found, or it has already been sent.")

    def set_campaign_status(self, tenant_id: str, campaign_id: str, campaign_status: str) -> None:
        now = _utc_now()
        with self.connection() as conn:
            result = conn.execute(
                "UPDATE campaigns SET status = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (campaign_status, now, campaign_id, tenant_id),
            )
        if result.rowcount != 1:
            raise TenantStoreError("Campaign was not found for this workspace.")

    def save_contacts(self, tenant_id: str, contacts: list[dict]) -> list[dict]:
        now = _utc_now()
        saved = []
        with self.connection() as conn:
            for contact in contacts:
                email = contact["email"].strip().lower()
                contact_id = f"contact_{secrets.token_urlsafe(12)}"
                conn.execute(
                    """
                    INSERT INTO contacts (id, tenant_id, email, data_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, email) DO UPDATE SET
                        data_json = excluded.data_json, updated_at = excluded.updated_at
                    """,
                    (contact_id, tenant_id, email, json.dumps(contact), now, now),
                )
                saved.append({"email": email, "updated_at": now})
        return saved

    def list_contacts(self, tenant_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, email, data_json, created_at, updated_at
                FROM contacts WHERE tenant_id = ? ORDER BY email
                """,
                (tenant_id,),
            ).fetchall()
        contacts = []
        for row in rows:
            item = dict(row)
            data = json.loads(item.pop("data_json"))
            contacts.append({**item, **data})
        return contacts

    def delete_contact(self, tenant_id: str, contact_id: str) -> None:
        with self.connection() as conn:
            result = conn.execute(
                "DELETE FROM contacts WHERE id = ? AND tenant_id = ?",
                (contact_id, tenant_id),
            )
        if result.rowcount != 1:
            raise TenantStoreError("Contact was not found for this workspace.")

    def save_workspace_signature(self, tenant_id: str, signature_html: str | None) -> dict:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO workspace_settings (tenant_id, signature_html, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    signature_html = excluded.signature_html,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, signature_html, now),
            )
        return {"signature_configured": bool(signature_html), "updated_at": now}

    def get_workspace_signature(self, tenant_id: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT signature_html FROM workspace_settings WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
        return row["signature_html"] if row else None
