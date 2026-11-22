from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import uuid4

from fastapi import HTTPException

from .booking_adapter import BookingAdapter, EvidenceMismatch, UncertainOutcome
from .repository import change_status, get_operation, operation_view
from .security import Principal


def approve(database, principal: Principal, operation_id: str, valid_for_seconds: int):
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=valid_for_seconds)
    with database.connect() as connection:
        operation = get_operation(connection, principal.organization_id, operation_id, lock=True)
        if operation["status"] != "awaiting_approval":
            raise HTTPException(409, "Operation is not awaiting approval.")
        approval_id = uuid4()
        connection.execute(
            """INSERT INTO sentinel_approvals (
                   approval_id, operation_id, organization_id, action_hash,
                   state, approved_by_key_id, expires_at
               ) VALUES (%s, %s, %s, %s, 'approved', %s, %s)""",
            (approval_id, operation["operation_id"], operation["organization_id"],
             operation["action_hash"], principal.api_key_id, expires_at),
        )
        change_status(connection, operation, "authorized", "approval.granted", {}, principal)
    return {"approval_id": approval_id, "operation_id": operation["operation_id"],
            "state": "approved", "expires_at": expires_at}


def revoke(database, principal: Principal, operation_id: str):
    with database.connect() as connection:
        operation = get_operation(connection, principal.organization_id, operation_id, lock=True)
        if operation["status"] != "authorized":
            raise HTTPException(409, "Only an authorized operation can be revoked.")
        approval = connection.execute(
            """SELECT * FROM sentinel_approvals
               WHERE operation_id=%s AND state='approved'
               ORDER BY approved_at DESC LIMIT 1 FOR UPDATE""",
            (operation["operation_id"],),
        ).fetchone()
        if approval is None:
            raise HTTPException(409, "No active approval exists.")
        connection.execute(
            "UPDATE sentinel_approvals SET state='revoked', revoked_at=now() WHERE approval_id=%s",
            (approval["approval_id"],),
        )
        row = change_status(connection, operation, "awaiting_approval", "approval.revoked", {}, principal)
    return operation_view(row)


def reject(database, principal: Principal, operation_id: str):
    with database.connect() as connection:
        operation = get_operation(connection, principal.organization_id, operation_id, lock=True)
        if operation["status"] != "awaiting_approval":
            raise HTTPException(409, "Operation is not awaiting approval.")
        row = change_status(connection, operation, "rejected", "operation.rejected", {}, principal)
    return operation_view(row)


def claim_for_execution(database, principal: Principal, operation_id: str,
                        lease_seconds: int = 30) -> dict:
    with database.connect() as connection:
        operation = get_operation(connection, principal.organization_id, operation_id, lock=True)
        if operation["status"] != "authorized":
            raise HTTPException(409, "Operation is not authorized for execution.")
        approval = connection.execute(
            """SELECT * FROM sentinel_approvals
               WHERE operation_id=%s AND state='approved' AND action_hash=%s
               ORDER BY approved_at DESC LIMIT 1 FOR UPDATE""",
            (operation["operation_id"], operation["action_hash"]),
        ).fetchone()
        now = datetime.now(timezone.utc)
        if approval is None or approval["expires_at"] <= now:
            if approval is not None:
                connection.execute(
                    "UPDATE sentinel_approvals SET state='revoked', revoked_at=now() WHERE approval_id=%s",
                    (approval["approval_id"],),
                )
            change_status(connection, operation, "awaiting_approval", "approval.expired", {}, principal)
            raise HTTPException(409, "Approval is absent or expired; request approval again.")
        connection.execute(
            "UPDATE sentinel_approvals SET state='consumed', consumed_at=now() WHERE approval_id=%s",
            (approval["approval_id"],),
        )
        operation = change_status(
            connection, operation, "executing", "execution.started",
            {"approval_id": str(approval["approval_id"])}, principal,
        )
        attempt_id = uuid4()
        operation = connection.execute(
            """UPDATE sentinel_operations
               SET current_attempt_id=%s,
                   lease_expires_at=now() + (%s * interval '1 second')
               WHERE operation_id=%s RETURNING *""",
            (attempt_id, lease_seconds, operation["operation_id"]),
        ).fetchone()
    return operation


def renew_lease(database, principal: Principal, operation: dict,
                expected_status: str, lease_seconds: int) -> bool:
    with database.connect() as connection:
        row = connection.execute(
            """UPDATE sentinel_operations
               SET lease_expires_at=now() + (%s * interval '1 second')
               WHERE operation_id=%s AND organization_id=%s AND status=%s
                 AND current_attempt_id=%s
               RETURNING operation_id""",
            (
                lease_seconds, operation["operation_id"], principal.organization_id,
                expected_status, operation["current_attempt_id"],
            ),
        ).fetchone()
    return row is not None


@contextmanager
def maintain_lease(database, principal: Principal, operation: dict,
                   expected_status: str, lease_seconds: int,
                   *, heartbeat_seconds: float | None = None):
    """Renew ownership while a slow external request is in flight."""
    stop = Event()
    interval = heartbeat_seconds or max(1.0, lease_seconds / 3)

    def heartbeat():
        while not stop.wait(interval):
            try:
                if not renew_lease(
                    database, principal, operation, expected_status, lease_seconds
                ):
                    return
            except Exception:
                # The finishing transaction still checks the attempt ID. If the
                # database was briefly unavailable, it will either safely commit
                # the same owner's result or reject a stale owner.
                return

    thread = Thread(target=heartbeat, name="sentinel-lease-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=interval + 1)


def finish_execution(database, principal, original, status, event_type, details,
                     *, external_id=None, last_error=None):
    with database.connect() as connection:
        current = get_operation(
            connection, principal.organization_id, str(original["operation_id"]), lock=True
        )
        if (current["status"] != "executing"
                or current["current_attempt_id"] != original["current_attempt_id"]):
            raise HTTPException(409, "Execution ownership changed; the result was not applied.")
        row = change_status(
            connection, current, status, event_type, details, principal,
            external_id=external_id, last_error=last_error,
        )
        connection.execute(
            """UPDATE sentinel_operations
               SET current_attempt_id=NULL, lease_expires_at=NULL WHERE operation_id=%s""",
            (current["operation_id"],),
        )
    return operation_view(row)


def execute(database, principal: Principal, operation_id: str, adapter: BookingAdapter,
            lease_seconds: int = 30):
    prepare = getattr(adapter, "prepare_execution", None)
    if callable(prepare):
        prepare()
    operation = claim_for_execution(database, principal, operation_id, lease_seconds)
    try:
        with maintain_lease(database, principal, operation, "executing", lease_seconds):
            external_id = adapter.execute(
                str(operation["operation_id"]), operation["action_payload"]
            )
    except (UncertainOutcome, EvidenceMismatch) as error:
        return finish_execution(
            database, principal, operation, "unknown", "execution.outcome_unknown",
            {"reason": type(error).__name__},
            last_error="External result could not be confirmed.",
        )
    return finish_execution(
        database, principal, operation, "succeeded", "execution.succeeded", {},
        external_id=external_id,
    )


def claim_for_reconciliation(database, principal: Principal, operation_id: str,
                             lease_seconds: int = 30) -> dict:
    with database.connect() as connection:
        operation = get_operation(connection, principal.organization_id, operation_id, lock=True)
        if operation["status"] not in ("unknown", "executing"):
            raise HTTPException(409, "Only an uncertain or interrupted operation can be reconciled.")
        now = datetime.now(timezone.utc)
        if operation["status"] == "executing":
            if operation["lease_expires_at"] is not None and operation["lease_expires_at"] > now:
                raise HTTPException(409, "The execution worker still owns an active lease.")
            operation = change_status(
                connection, operation, "unknown", "execution.interrupted",
                {"expired_attempt_id": str(operation["current_attempt_id"])}, principal,
                last_error="Execution ended without a recorded result.",
            )
        elif (operation["current_attempt_id"] is not None
              and operation["lease_expires_at"] is not None
              and operation["lease_expires_at"] > now):
            raise HTTPException(409, "Another worker is reconciling this operation.")
        reconciliation_id = uuid4()
        operation = connection.execute(
            """UPDATE sentinel_operations
               SET current_attempt_id=%s,
                   lease_expires_at=now() + (%s * interval '1 second')
               WHERE operation_id=%s RETURNING *""",
            (reconciliation_id, lease_seconds, operation["operation_id"]),
        ).fetchone()
    return operation


def finish_reconciliation(database, principal, original, status, event_type, details,
                          *, external_id=None, last_error=None):
    with database.connect() as connection:
        current = get_operation(
            connection, principal.organization_id, str(original["operation_id"]), lock=True
        )
        if (current["status"] != "unknown"
                or current["current_attempt_id"] != original["current_attempt_id"]):
            raise HTTPException(409, "Reconciliation ownership changed; the result was not applied.")
        row = change_status(
            connection, current, status, event_type, details, principal,
            external_id=external_id, last_error=last_error,
        )
        connection.execute(
            """UPDATE sentinel_operations
               SET current_attempt_id=NULL, lease_expires_at=NULL WHERE operation_id=%s""",
            (current["operation_id"],),
        )
    return operation_view(row)


def reconcile(database, principal: Principal, operation_id: str, adapter: BookingAdapter,
              lease_seconds: int = 30):
    operation = claim_for_reconciliation(database, principal, operation_id, lease_seconds)
    try:
        with maintain_lease(database, principal, operation, "unknown", lease_seconds):
            external_id = adapter.reconcile(
                str(operation["operation_id"]), operation["action_payload"]
            )
    except (UncertainOutcome, EvidenceMismatch) as error:
        return finish_reconciliation(
            database, principal, operation, "needs_review", "reconciliation.unresolved",
            {"reason": type(error).__name__},
            last_error="Automatic reconciliation could not prove the outcome.",
        )
    return finish_reconciliation(
        database, principal, operation, "succeeded", "reconciliation.succeeded", {},
        external_id=external_id,
    )
