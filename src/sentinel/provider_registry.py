from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .schemas import OpenAIProviderCreate
from .security import Principal


def provider_view(row: dict) -> dict:
    return {key: row[key] for key in (
        "provider_id", "model_alias", "provider", "model_id", "key_hint",
        "status", "created_at", "updated_at",
    )}


class CredentialCipher:
    def __init__(self, key: str):
        try:
            self.fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise RuntimeError(
                "SENTINEL_CREDENTIAL_ENCRYPTION_KEY must be a Fernet-compatible key."
            ) from error

    def encrypt(self, secret: str) -> bytes:
        return self.fernet.encrypt(secret.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self.fernet.decrypt(bytes(ciphertext)).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise RuntimeError("Stored model credential cannot be decrypted.") from error


def _add_event(connection, principal: Principal, row: dict, event_type: str) -> None:
    connection.execute(
        """INSERT INTO sentinel_model_provider_events
           (provider_id, organization_id, event_type, details, actor_key_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (row["provider_id"], principal.organization_id, event_type,
         Jsonb({"model_alias": row["model_alias"], "model_id": row["model_id"]}),
         principal.api_key_id),
    )


def configure_openai_provider(database, cipher: CredentialCipher, principal: Principal,
                              body: OpenAIProviderCreate) -> tuple[dict, bool]:
    api_key = body.api_key.get_secret_value()
    encrypted = cipher.encrypt(api_key)
    hint = "…" + api_key[-4:]
    with database.connect() as connection:
        existing = connection.execute(
            """SELECT * FROM sentinel_model_provider_credentials
               WHERE organization_id=%s AND model_alias=%s FOR UPDATE""",
            (principal.organization_id, body.model_alias),
        ).fetchone()
        if existing is None:
            row = connection.execute(
                """INSERT INTO sentinel_model_provider_credentials
                   (provider_id, organization_id, model_alias, provider, model_id,
                    encrypted_api_key, key_hint, created_by_key_id)
                   VALUES (%s, %s, %s, 'openai', %s, %s, %s, %s) RETURNING *""",
                (uuid4(), principal.organization_id, body.model_alias, body.model_id,
                 encrypted, hint, principal.api_key_id),
            ).fetchone()
            created = True
            event_type = "model_provider.configured"
        else:
            row = connection.execute(
                """UPDATE sentinel_model_provider_credentials
                   SET provider='openai', model_id=%s, encrypted_api_key=%s,
                       key_hint=%s, status='active', updated_at=now()
                   WHERE provider_id=%s RETURNING *""",
                (body.model_id, encrypted, hint, existing["provider_id"]),
            ).fetchone()
            created = False
            event_type = "model_provider.rotated"
        _add_event(connection, principal, row, event_type)
    return provider_view(row), created


def list_model_providers(database, principal: Principal) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT * FROM sentinel_model_provider_credentials
               WHERE organization_id=%s ORDER BY model_alias""",
            (principal.organization_id,),
        ).fetchall()
    return [provider_view(row) for row in rows]


def get_model_credential(database, cipher: CredentialCipher, organization_id: str,
                         model_alias: str) -> dict:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM sentinel_model_provider_credentials
               WHERE organization_id=%s AND model_alias=%s AND status='active'""",
            (organization_id, model_alias),
        ).fetchone()
    if row is None:
        raise HTTPException(409, f"No active provider is configured for '{model_alias}'.")
    row["api_key"] = cipher.decrypt(row["encrypted_api_key"])
    return row


def list_model_invocations(database, principal: Principal, run_id: str) -> list[dict]:
    with database.connect() as connection:
        run = connection.execute(
            "SELECT run_id FROM sentinel_runs WHERE run_id=%s AND organization_id=%s",
            (run_id, principal.organization_id),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found.")
        return connection.execute(
            """SELECT invocation_id, run_id, model_alias, provider, model_id, status,
                      provider_response_id, input_tokens, output_tokens, total_tokens,
                      duration_ms, error_class, created_at
               FROM sentinel_model_invocations WHERE run_id=%s ORDER BY created_at""",
            (run["run_id"],),
        ).fetchall()
