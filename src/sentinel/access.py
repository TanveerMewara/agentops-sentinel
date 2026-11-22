"""Organization-admin key lifecycle. Plaintext tokens are returned once."""
from datetime import datetime, timezone
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .security import digest_key, require_roles


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=100)
    role: Literal["admin", "developer", "reviewer", "worker"]
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def future_expiration(self):
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at <= datetime.now(timezone.utc):
                raise ValueError("Expiration must be a future time with a timezone.")
        return self


KEY_FIELDS = "api_key_id, key_prefix, label, role, expires_at, revoked_at, created_at"


def lock_admin(connection, principal):
    connection.execute("SELECT organization_id FROM sentinel_organizations WHERE organization_id=%s FOR UPDATE",
                       (principal.organization_id,))
    active = connection.execute(
        """SELECT 1 FROM sentinel_api_keys WHERE api_key_id=%s AND organization_id=%s
           AND role='admin' AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at>clock_timestamp())""",
        (principal.api_key_id, principal.organization_id),
    ).fetchone()
    if active is None:
        raise HTTPException(401, "Administrator key is no longer active.")


def identity(database, principal):
    with database.connect() as connection:
        org = connection.execute("SELECT name FROM sentinel_organizations WHERE organization_id=%s",
                                 (principal.organization_id,)).fetchone()
        member = (connection.execute("SELECT handle,display_name FROM sentinel_members WHERE member_id=%s AND organization_id=%s",
                                     (principal.member_id,principal.organization_id)).fetchone()
                  if principal.member_id else None)
    return {"organization_id": principal.organization_id, "organization_name": org["name"],
            "role": principal.role, "api_key_id": principal.api_key_id,
            'auth_kind':principal.auth_kind,'member':member}


def list_keys(database, principal):
    require_roles("admin")(principal)
    with database.connect() as connection:
        return connection.execute(f"SELECT {KEY_FIELDS} FROM sentinel_api_keys WHERE organization_id=%s AND key_kind='service' ORDER BY created_at DESC",
                                  (principal.organization_id,)).fetchall()


def create_key(database, pepper, principal, body):
    require_roles("admin")(principal)
    prefix = "snt_" + secrets.token_hex(12)
    token = prefix + "_" + secrets.token_urlsafe(32)
    with database.connect() as connection:
        # Same organization lock as revocation serializes administrator changes.
        lock_admin(connection, principal)
        if body.expires_at is not None and body.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(409, "Key expiration passed while waiting; choose a later time.")
        row = connection.execute(
            f"""INSERT INTO sentinel_api_keys(api_key_id, organization_id, key_prefix, key_digest, label, role, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {KEY_FIELDS}""",
            (uuid4(), principal.organization_id, prefix, digest_key(token, pepper), body.label, body.role, body.expires_at),
        ).fetchone()
        connection.execute("INSERT INTO sentinel_access_events(organization_id,target_key_id,actor_key_id,event_type) VALUES (%s,%s,%s,'key.created')",
                           (principal.organization_id, row["api_key_id"], principal.api_key_id))
    return {"key": row, "token": token}


def revoke_key(database, principal, key_id):
    require_roles("admin")(principal)
    with database.connect() as connection:
        lock_admin(connection, principal)
        row = connection.execute(f"SELECT {KEY_FIELDS} FROM sentinel_api_keys WHERE api_key_id=%s AND organization_id=%s FOR UPDATE",
                                 (key_id, principal.organization_id)).fetchone()
        if row is None:
            raise HTTPException(404, "API key not found.")
        if row["revoked_at"] is not None:
            return row
        if row["role"] == "admin":
            remaining = connection.execute(
                """SELECT count(*) AS n FROM sentinel_api_keys WHERE organization_id=%s
                   AND api_key_id<>%s AND role='admin' AND revoked_at IS NULL
                   AND (expires_at IS NULL OR expires_at>clock_timestamp())""", (principal.organization_id, key_id),
            ).fetchone()["n"]
            if remaining == 0:
                raise HTTPException(409, "Create another active administrator key before revoking this one.")
        row = connection.execute(f"UPDATE sentinel_api_keys SET revoked_at=now() WHERE api_key_id=%s RETURNING {KEY_FIELDS}", (key_id,)).fetchone()
        connection.execute("INSERT INTO sentinel_access_events(organization_id,target_key_id,actor_key_id,event_type) VALUES (%s,%s,%s,'key.revoked')",
                           (principal.organization_id, key_id, principal.api_key_id))
    return row


def access_events(database, principal, limit):
    require_roles("admin")(principal)
    with database.connect() as connection:
        return connection.execute("SELECT event_id,target_key_id,actor_key_id,event_type,created_at FROM sentinel_access_events WHERE organization_id=%s ORDER BY event_id DESC LIMIT %s",
                                  (principal.organization_id, limit)).fetchall()
