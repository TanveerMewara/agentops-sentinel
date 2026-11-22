import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .schemas import OperationCreate
from .security import Principal


def canonical_action_hash(action_type: str, action: dict) -> str:
    value = json.dumps(
        {"action_type": action_type, "action": action},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def operation_view(row: dict) -> dict:
    return {
        "operation_id": row["operation_id"],
        "idempotency_key": row["idempotency_key"],
        "action_type": row["action_type"],
        "action": row["action_payload"],
        "status": row["status"],
        "external_id": row["external_id"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_operation(database, principal: Principal, request: OperationCreate) -> tuple[dict, bool]:
    action = request.action.model_dump()
    action_hash = canonical_action_hash(request.action_type, action)
    operation_id = uuid4()
    with database.connect() as connection:
        row = connection.execute(
            """INSERT INTO sentinel_operations (
                   operation_id, organization_id, idempotency_key, action_type,
                   action_payload, action_hash, status, created_by_key_id
               ) VALUES (%s, %s, %s, %s, %s, %s, 'awaiting_approval', %s)
               ON CONFLICT (organization_id, idempotency_key) DO NOTHING
               RETURNING *""",
            (
                operation_id, principal.organization_id, request.idempotency_key,
                request.action_type, Jsonb(action), action_hash, principal.api_key_id,
            ),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute(
                """SELECT * FROM sentinel_operations
                   WHERE organization_id = %s AND idempotency_key = %s""",
                (principal.organization_id, request.idempotency_key),
            ).fetchone()
            if row["action_hash"] != action_hash:
                raise HTTPException(409, "Idempotency key already represents a different action.")
        else:
            add_event(connection, row, "operation.created", None, "awaiting_approval", {}, principal)
    return operation_view(row), created


def get_operation(connection, organization_id: str, operation_id: str, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    row = connection.execute(
        "SELECT * FROM sentinel_operations WHERE organization_id = %s AND operation_id = %s" + suffix,
        (organization_id, operation_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Operation not found.")
    return row


def add_event(connection, operation: dict, event_type: str, from_status: str | None,
              to_status: str, details: dict, principal: Principal | None = None):
    connection.execute(
        """INSERT INTO sentinel_operation_events (
               operation_id, organization_id, event_type, from_status,
               to_status, details, actor_key_id
           ) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            operation["operation_id"], operation["organization_id"], event_type,
            from_status, to_status, Jsonb(details),
            principal.api_key_id if principal else None,
        ),
    )


def change_status(connection, operation: dict, status: str, event_type: str,
                  details: dict, principal: Principal | None = None,
                  *, external_id=None, last_error=None):
    previous = operation["status"]
    row = connection.execute(
        """UPDATE sentinel_operations
           SET status = %s, external_id = COALESCE(%s, external_id),
               last_error = %s, updated_at = now()
           WHERE operation_id = %s RETURNING *""",
        (status, external_id, last_error, operation["operation_id"]),
    ).fetchone()
    add_event(connection, row, event_type, previous, status, details, principal)
    return row
