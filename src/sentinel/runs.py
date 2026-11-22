from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Event, Thread
from uuid import UUID, uuid4

from fastapi import HTTPException
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb

from .booking_adapter import BookingAdapter, EvidenceMismatch, UncertainOutcome
from .adapters import AdapterRegistry, registry_for
from .schemas import AgentVersionCreate, RunCreate, ToolCallReserve
from .security import Principal


TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled", "needs_review"}


def agent_version_view(row: dict) -> dict:
    return {key: row[key] for key in (
        "agent_version_id", "agent_id", "version", "instructions",
        "model_alias", "max_steps", "created_at",
    )}


def run_view(row: dict) -> dict:
    result = {key: row[key] for key in (
        "run_id", "agent_id", "agent_version_id", "idempotency_key", "status",
        "max_steps", "steps_used", "created_at", "started_at", "completed_at",
        "updated_at",
    )}
    result["input"] = row["input_payload"]
    return result


def tool_call_view(row: dict) -> dict:
    return {key: row[key] for key in (
        "tool_call_id", "run_id", "tool_id", "idempotency_key", "sequence",
        "arguments", "status", "requires_approval", "result", "error", "external_id",
        "created_at", "completed_at",
    )}


def canonical_tool_call_hash(run_id, tool_id, arguments: dict, contract: dict) -> str:
    value = json.dumps({
        "run_id": str(run_id),
        "tool_id": str(tool_id),
        "tool": {"name": contract["name"], "version": contract["version"]},
        "arguments": arguments,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def add_run_event(connection, principal: Principal, run_id, event_type: str,
                  details: dict) -> None:
    connection.execute(
        """INSERT INTO sentinel_run_events
           (run_id, organization_id, event_type, details, actor_key_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (run_id, principal.organization_id, event_type, Jsonb(details), principal.api_key_id),
    )


def validate_payload(payload: dict, schema: dict, label: str) -> None:
    error = next(Draft202012Validator(schema).iter_errors(payload), None)
    if error is None:
        return
    raise HTTPException(422, detail={
        "message": f"{label} does not match the frozen tool contract.",
        # Values and dynamic field names can contain PII or credentials.
        "path": "$",
        "validation_error": "Payload validation failed.",
    })


def create_agent_version(database, principal: Principal, agent_id: str,
                         body: AgentVersionCreate) -> tuple[dict, bool]:
    with database.connect() as connection:
        agent = connection.execute(
            """SELECT agent_id, status FROM sentinel_agents
               WHERE agent_id=%s AND organization_id=%s FOR UPDATE""",
            (agent_id, principal.organization_id),
        ).fetchone()
        if agent is None:
            raise HTTPException(404, "Agent not found.")
        if agent["status"] != "active":
            raise HTTPException(409, "A disabled agent cannot receive a new version.")
        row = connection.execute(
            """INSERT INTO sentinel_agent_versions
               (agent_version_id, agent_id, organization_id, version, instructions,
                model_alias, max_steps, created_by_key_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (agent_id, version) DO NOTHING RETURNING *""",
            (uuid4(), agent["agent_id"], principal.organization_id, body.version,
             body.instructions, body.model_alias, body.max_steps, principal.api_key_id),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute(
                "SELECT * FROM sentinel_agent_versions WHERE agent_id=%s AND version=%s",
                (agent["agent_id"], body.version),
            ).fetchone()
            comparable = {key: row[key] for key in (
                "version", "instructions", "model_alias", "max_steps",
            )}
            if comparable != body.model_dump():
                raise HTTPException(409, "Agent version already represents another configuration.")
    return agent_version_view(row), created


def list_agent_versions(database, principal: Principal, agent_id: str) -> list[dict]:
    with database.connect() as connection:
        agent = connection.execute(
            "SELECT agent_id FROM sentinel_agents WHERE agent_id=%s AND organization_id=%s",
            (agent_id, principal.organization_id),
        ).fetchone()
        if agent is None:
            raise HTTPException(404, "Agent not found.")
        rows = connection.execute(
            """SELECT * FROM sentinel_agent_versions WHERE agent_id=%s
               ORDER BY created_at, agent_version_id""",
            (agent["agent_id"],),
        ).fetchall()
    return [agent_version_view(row) for row in rows]


def create_run(database, principal: Principal, body: RunCreate) -> tuple[dict, bool]:
    with database.connect() as connection:
        version = connection.execute(
            """SELECT av.*, a.status AS agent_status
               FROM sentinel_agent_versions av
               JOIN sentinel_agents a ON a.agent_id=av.agent_id
               WHERE av.agent_version_id=%s AND av.organization_id=%s FOR UPDATE OF av, a""",
            (body.agent_version_id, principal.organization_id),
        ).fetchone()
        if version is None:
            raise HTTPException(404, "Agent version not found.")
        if version["agent_status"] != "active":
            raise HTTPException(409, "A disabled agent cannot start a run.")
        row = connection.execute(
            """INSERT INTO sentinel_runs
               (run_id, organization_id, agent_id, agent_version_id, idempotency_key,
                input_payload, max_steps, created_by_key_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (organization_id, idempotency_key) DO NOTHING RETURNING *""",
            (uuid4(), principal.organization_id, version["agent_id"],
             version["agent_version_id"], body.idempotency_key, Jsonb(body.input),
             version["max_steps"], principal.api_key_id),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute(
                """SELECT * FROM sentinel_runs
                   WHERE organization_id=%s AND idempotency_key=%s""",
                (principal.organization_id, body.idempotency_key),
            ).fetchone()
            if (row["agent_version_id"], row["input_payload"]) != (
                body.agent_version_id, body.input
            ):
                raise HTTPException(409, "Run idempotency key already represents another request.")
            return run_view(row), False

        snapshots = connection.execute(
            """INSERT INTO sentinel_run_tool_permissions
               (run_id, tool_id, organization_id, contract_snapshot, max_calls)
               SELECT %s, t.tool_id, t.organization_id,
                      jsonb_build_object(
                          'name', t.name, 'version', t.version,
                          'description', t.description,
                          'input_schema', t.input_schema,
                          'output_schema', t.output_schema,
                          'risk_level', t.risk_level,
                          'approval_mode', t.approval_mode
                      ), grants.max_calls_per_run
               FROM sentinel_agent_tools grants
               JOIN sentinel_tools t ON t.tool_id=grants.tool_id
               WHERE grants.agent_id=%s AND grants.organization_id=%s
                 AND t.status='active'
               RETURNING tool_id""",
            (row["run_id"], version["agent_id"], principal.organization_id),
        ).fetchall()
        add_run_event(connection, principal, row["run_id"], "run.created", {
            "agent_version_id": str(version["agent_version_id"]),
            "tool_permissions_snapshotted": len(snapshots),
            "max_steps": version["max_steps"],
        })
    return run_view(row), True


def get_run(connection, organization_id: str, run_id: str, for_update: bool = False) -> dict:
    suffix = " FOR UPDATE" if for_update else ""
    row = connection.execute(
        "SELECT * FROM sentinel_runs WHERE run_id=%s AND organization_id=%s" + suffix,
        (run_id, organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found.")
    return row


def read_run(database, principal: Principal, run_id: str) -> dict:
    with database.connect() as connection:
        return run_view(get_run(connection, principal.organization_id, run_id))


def list_runs(database, principal: Principal, limit: int, run_status: str | None) -> list[dict]:
    with database.connect() as connection:
        if run_status is None:
            rows = connection.execute(
                """SELECT * FROM sentinel_runs WHERE organization_id=%s
                   ORDER BY created_at DESC, run_id LIMIT %s""",
                (principal.organization_id, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT * FROM sentinel_runs WHERE organization_id=%s AND status=%s
                   ORDER BY created_at DESC, run_id LIMIT %s""",
                (principal.organization_id, run_status, limit),
            ).fetchall()
    return [run_view(row) for row in rows]


def reserve_tool_call(database, principal: Principal, run_id: str,
                      body: ToolCallReserve) -> tuple[dict, bool]:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id, for_update=True)
        existing = connection.execute(
            """SELECT * FROM sentinel_tool_calls
               WHERE run_id=%s AND idempotency_key=%s""",
            (run["run_id"], body.idempotency_key),
        ).fetchone()
        if existing is not None:
            if (existing["tool_id"], existing["arguments"]) != (body.tool_id, body.arguments):
                raise HTTPException(409, "Tool-call idempotency key represents another request.")
            return tool_call_view(existing), False
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise HTTPException(409, f"Run is already {run['status']}.")
        permission = connection.execute(
            """SELECT * FROM sentinel_run_tool_permissions
               WHERE run_id=%s AND tool_id=%s AND organization_id=%s FOR UPDATE""",
            (run["run_id"], body.tool_id, principal.organization_id),
        ).fetchone()
        if permission is None:
            raise HTTPException(409, "Tool is not permitted by this run's frozen configuration.")
        if run["steps_used"] >= run["max_steps"]:
            raise HTTPException(409, "Run step budget is exhausted.")
        if permission["calls_used"] >= permission["max_calls"]:
            raise HTTPException(409, "Tool call budget is exhausted for this run.")
        validate_payload(body.arguments, permission["contract_snapshot"]["input_schema"], "Arguments")

        sequence = run["steps_used"] + 1
        contract = permission["contract_snapshot"]
        requires_approval = (
            contract["approval_mode"] == "always"
            or (contract["approval_mode"] == "risk_based"
                and contract["risk_level"] in ("medium", "high"))
        )
        call_status = "awaiting_approval" if requires_approval else "authorized"
        action_hash = canonical_tool_call_hash(
            run["run_id"], body.tool_id, body.arguments, contract
        )
        row = connection.execute(
            """INSERT INTO sentinel_tool_calls
               (tool_call_id, run_id, tool_id, organization_id, idempotency_key,
                sequence, arguments, status, requires_approval, action_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (uuid4(), run["run_id"], body.tool_id, principal.organization_id,
             body.idempotency_key, sequence, Jsonb(body.arguments), call_status,
             requires_approval, action_hash),
        ).fetchone()
        connection.execute(
            """UPDATE sentinel_runs SET steps_used=steps_used+1, status='running',
                      started_at=COALESCE(started_at, now()), updated_at=now()
               WHERE run_id=%s""",
            (run["run_id"],),
        )
        connection.execute(
            """UPDATE sentinel_run_tool_permissions SET calls_used=calls_used+1
               WHERE run_id=%s AND tool_id=%s""",
            (run["run_id"], body.tool_id),
        )
        add_run_event(connection, principal, run["run_id"], "tool_call.reserved", {
            "tool_call_id": str(row["tool_call_id"]),
            "tool_id": str(body.tool_id), "sequence": sequence,
            "status": call_status, "requires_approval": requires_approval,
        })
    return tool_call_view(row), True


def _locked_tool_call(connection, organization_id: str, run_id: str,
                      tool_call_id: str) -> tuple[dict, dict]:
    get_run(connection, organization_id, run_id, for_update=True)
    row = connection.execute(
        """SELECT tc.*, permission.contract_snapshot
           FROM sentinel_tool_calls tc
           JOIN sentinel_run_tool_permissions permission
             ON permission.run_id=tc.run_id AND permission.tool_id=tc.tool_id
           WHERE tc.tool_call_id=%s AND tc.run_id=%s AND tc.organization_id=%s
           FOR UPDATE OF tc""",
        (tool_call_id, run_id, organization_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Tool call not found.")
    return row, row["contract_snapshot"]


def finish_run(database, principal: Principal, run_id: str) -> dict:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id, for_update=True)
        if run["status"] == "succeeded":
            return run_view(run)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise HTTPException(409, f"Run is already {run['status']}.")
        pending = connection.execute(
            """SELECT 1 FROM sentinel_tool_calls
               WHERE run_id=%s AND status IN (
                   'reserved', 'awaiting_approval', 'authorized', 'executing', 'unknown'
               ) LIMIT 1""",
            (run["run_id"],),
        ).fetchone()
        if pending is not None:
            raise HTTPException(409, "Run still has a reserved tool call.")
        run = connection.execute(
            """UPDATE sentinel_runs SET status='succeeded', completed_at=now(),
                      updated_at=now() WHERE run_id=%s RETURNING *""",
            (run["run_id"],),
        ).fetchone()
        add_run_event(connection, principal, run["run_id"], "run.succeeded", {
            "steps_used": run["steps_used"],
        })
    return run_view(run)


def cancel_run(database, principal: Principal, run_id: str, reason: str) -> dict:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id, for_update=True)
        if run["status"] == "cancelled":
            return run_view(run)
        if run["status"] in TERMINAL_RUN_STATUSES:
            raise HTTPException(409, f"Run is already {run['status']}.")
        unresolved = connection.execute(
            """SELECT 1 FROM sentinel_tool_calls
               WHERE run_id=%s AND status IN ('executing', 'unknown') LIMIT 1""",
            (run["run_id"],),
        ).fetchone()
        if unresolved is not None:
            raise HTTPException(409, "Run has an execution outcome to reconcile.")
        connection.execute(
            """UPDATE sentinel_tool_call_approvals SET state='revoked',
                      revoked_at=now()
               WHERE tool_call_id IN (
                   SELECT tool_call_id FROM sentinel_tool_calls
                   WHERE run_id=%s AND status IN
                     ('reserved', 'awaiting_approval', 'authorized')
               ) AND state='approved'""",
            (run["run_id"],),
        )
        cancelled = connection.execute(
            """UPDATE sentinel_tool_calls SET status='cancelled',
                      error='Parent run cancelled.', completed_at=now()
               WHERE run_id=%s AND status IN
                 ('reserved', 'awaiting_approval', 'authorized')
               RETURNING tool_call_id""",
            (run["run_id"],),
        ).fetchall()
        run = connection.execute(
            """UPDATE sentinel_runs SET status='cancelled', completed_at=now(),
                      updated_at=now() WHERE run_id=%s RETURNING *""",
            (run["run_id"],),
        ).fetchone()
        add_run_event(connection, principal, run["run_id"], "run.cancelled", {
            "reason": reason,
            "cancelled_tool_call_ids": [
                str(row["tool_call_id"]) for row in cancelled
            ],
        })
    return run_view(run)


def list_tool_calls(database, principal: Principal, run_id: str) -> list[dict]:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id)
        rows = connection.execute(
            "SELECT * FROM sentinel_tool_calls WHERE run_id=%s ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
    return [tool_call_view(row) for row in rows]


def list_organization_tool_calls(database, principal: Principal, call_status: str,
                                 limit: int, adapters=None) -> list[dict]:
    runtime = registry_for(adapters or BookingAdapter("http://127.0.0.1:8002"))
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT calls.* FROM sentinel_tool_calls calls
               JOIN sentinel_run_tool_permissions permission
                 ON permission.run_id=calls.run_id AND permission.tool_id=calls.tool_id
               WHERE calls.organization_id=%s AND calls.status=%s
                 AND EXISTS (SELECT 1 FROM jsonb_array_elements(%s::jsonb) accepted
                             WHERE permission.contract_snapshot @> accepted)
               ORDER BY calls.created_at, calls.tool_call_id LIMIT %s""",
            (principal.organization_id, call_status, Jsonb(runtime.discovery_filters()), limit),
        ).fetchall()
    return [tool_call_view(row) for row in rows]


def list_run_events(database, principal: Principal, run_id: str) -> list[dict]:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id)
        return connection.execute(
            """SELECT event_id, event_type, details, created_at FROM sentinel_run_events
               WHERE run_id=%s ORDER BY event_id""",
            (run["run_id"],),
        ).fetchall()


def approve_tool_call(database, principal: Principal, run_id: str, tool_call_id: str,
                      valid_for_seconds: int) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=valid_for_seconds)
    with database.connect() as connection:
        row, _ = _locked_tool_call(
            connection, principal.organization_id, run_id, tool_call_id
        )
        if not row["requires_approval"]:
            raise HTTPException(409, "This tool call does not require approval.")
        if row["status"] != "awaiting_approval":
            raise HTTPException(409, "Tool call is not awaiting approval.")
        approval_id = uuid4()
        connection.execute(
            """INSERT INTO sentinel_tool_call_approvals
               (approval_id, tool_call_id, organization_id, action_hash, state,
                approved_by_key_id, expires_at)
               VALUES (%s, %s, %s, %s, 'approved', %s, %s)""",
            (approval_id, row["tool_call_id"], principal.organization_id,
             row["action_hash"], principal.api_key_id, expires_at),
        )
        connection.execute(
            "UPDATE sentinel_tool_calls SET status='authorized' WHERE tool_call_id=%s",
            (row["tool_call_id"],),
        )
        add_run_event(connection, principal, run_id, "tool_call.approved", {
            "tool_call_id": str(row["tool_call_id"]),
            "approval_id": str(approval_id), "expires_at": expires_at.isoformat(),
        })
    return {"approval_id": approval_id, "tool_call_id": row["tool_call_id"],
            "state": "approved", "expires_at": expires_at}


def reject_tool_call(database, principal: Principal, run_id: str,
                     tool_call_id: str) -> dict:
    with database.connect() as connection:
        row, _ = _locked_tool_call(
            connection, principal.organization_id, run_id, tool_call_id
        )
        if row["status"] != "awaiting_approval":
            raise HTTPException(409, "Tool call is not awaiting approval.")
        row = connection.execute(
            """UPDATE sentinel_tool_calls SET status='cancelled',
                      error='Rejected by a human reviewer.', completed_at=now()
               WHERE tool_call_id=%s RETURNING *""",
            (row["tool_call_id"],),
        ).fetchone()
        add_run_event(connection, principal, run_id, "tool_call.rejected", {
            "tool_call_id": str(row["tool_call_id"]),
        })
    return tool_call_view(row)


def revoke_tool_call_approval(database, principal: Principal, run_id: str,
                              tool_call_id: str) -> dict:
    with database.connect() as connection:
        row, _ = _locked_tool_call(
            connection, principal.organization_id, run_id, tool_call_id
        )
        if not row["requires_approval"] or row["status"] != "authorized":
            raise HTTPException(409, "Tool call has no revocable approval.")
        approval = connection.execute(
            """SELECT * FROM sentinel_tool_call_approvals
               WHERE tool_call_id=%s AND state='approved'
               ORDER BY approved_at DESC LIMIT 1 FOR UPDATE""",
            (row["tool_call_id"],),
        ).fetchone()
        if approval is None:
            raise HTTPException(409, "Tool call has no active approval.")
        connection.execute(
            """UPDATE sentinel_tool_call_approvals SET state='revoked', revoked_at=now()
               WHERE approval_id=%s""",
            (approval["approval_id"],),
        )
        row = connection.execute(
            """UPDATE sentinel_tool_calls SET status='awaiting_approval'
               WHERE tool_call_id=%s RETURNING *""",
            (row["tool_call_id"],),
        ).fetchone()
        add_run_event(connection, principal, run_id, "tool_call.approval_revoked", {
            "tool_call_id": str(row["tool_call_id"]),
            "approval_id": str(approval["approval_id"]),
        })
    return tool_call_view(row)


def _require_supported_adapter(contract: dict, adapters=None) -> None:
    registry_for(adapters or BookingAdapter("http://127.0.0.1:8002")).resolve(contract)


def claim_tool_call(database, principal: Principal, run_id: str, tool_call_id: str,
                    lease_seconds: int, adapters=None) -> dict:
    expired = False
    with database.connect() as connection:
        row, contract = _locked_tool_call(
            connection, principal.organization_id, run_id, tool_call_id
        )
        run = get_run(connection, principal.organization_id, run_id)
        if run["status"] != "running":
            raise HTTPException(409, "Parent run is not active.")
        _require_supported_adapter(contract, adapters)
        registry_for(adapters or BookingAdapter("http://127.0.0.1:8002")).prepare_execution(contract)
        if contract["name"] == "book_viewing" and "property_id" in row["arguments"]:
            try:
                property_id = str(UUID(str(row["arguments"]["property_id"])))
            except (ValueError, TypeError, AttributeError) as error:
                raise HTTPException(422, "Property ID must be a UUID.") from error
            listing = connection.execute(
                """SELECT current_version, listing_status FROM estate_properties
                   WHERE property_id=%s AND organization_id=%s FOR SHARE""",
                (property_id, principal.organization_id),
            ).fetchone()
            if (listing is None or listing["listing_status"] != "active"
                    or listing["current_version"] != row["arguments"].get("property_version")):
                raise HTTPException(409, "Approved property version is unavailable; review the action.")
        if row["status"] != "authorized":
            raise HTTPException(409, "Tool call is not authorized for execution.")
        approval_id = None
        if row["requires_approval"]:
            approval = connection.execute(
                """SELECT * FROM sentinel_tool_call_approvals
                   WHERE tool_call_id=%s AND state='approved' AND action_hash=%s
                   ORDER BY approved_at DESC LIMIT 1 FOR UPDATE""",
                (row["tool_call_id"], row["action_hash"]),
            ).fetchone()
            now = datetime.now(timezone.utc)
            if approval is None or approval["expires_at"] <= now:
                if approval is not None:
                    connection.execute(
                        """UPDATE sentinel_tool_call_approvals SET state='revoked', revoked_at=now()
                           WHERE approval_id=%s""",
                        (approval["approval_id"],),
                    )
                connection.execute(
                    """UPDATE sentinel_tool_calls SET status='awaiting_approval'
                       WHERE tool_call_id=%s""",
                    (row["tool_call_id"],),
                )
                add_run_event(connection, principal, run_id, "tool_call.approval_expired", {
                    "tool_call_id": str(row["tool_call_id"]),
                })
                expired = True
            else:
                approval_id = approval["approval_id"]
                connection.execute(
                    """UPDATE sentinel_tool_call_approvals SET state='consumed', consumed_at=now()
                       WHERE approval_id=%s""",
                    (approval_id,),
                )
        if not expired:
            attempt_id = uuid4()
            row = connection.execute(
                """UPDATE sentinel_tool_calls SET status='executing', current_attempt_id=%s,
                          lease_expires_at=now() + (%s * interval '1 second'), error=NULL
                   WHERE tool_call_id=%s RETURNING *""",
                (attempt_id, lease_seconds, row["tool_call_id"]),
            ).fetchone()
            add_run_event(connection, principal, run_id, "tool_call.execution_started", {
                "tool_call_id": str(row["tool_call_id"]),
                "attempt_id": str(attempt_id),
                "approval_id": str(approval_id) if approval_id else None,
            })
            row["contract_snapshot"] = contract
    if expired:
        raise HTTPException(409, "Approval is absent or expired.")
    return row


def renew_tool_call_lease(database, principal: Principal, call: dict,
                          lease_seconds: int) -> bool:
    with database.connect() as connection:
        result = connection.execute(
            """UPDATE sentinel_tool_calls
               SET lease_expires_at=now() + (%s * interval '1 second')
               WHERE tool_call_id=%s AND organization_id=%s AND status IN ('executing', 'unknown')
                 AND current_attempt_id=%s RETURNING tool_call_id""",
            (lease_seconds, call["tool_call_id"], principal.organization_id,
             call["current_attempt_id"]),
        ).fetchone()
    return result is not None


@contextmanager
def maintain_tool_call_lease(database, principal: Principal, call: dict,
                             lease_seconds: int):
    stop = Event()
    interval = max(1.0, lease_seconds / 3)

    def heartbeat():
        while not stop.wait(interval):
            try:
                if not renew_tool_call_lease(database, principal, call, lease_seconds):
                    return
            except Exception:
                return

    thread = Thread(target=heartbeat, name="sentinel-tool-call-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=interval + 1)


def _finish_tool_execution(database, principal: Principal, original: dict, status: str,
                           event_type: str, *, result=None, external_id=None,
                           error=None) -> dict:
    with database.connect() as connection:
        current, _ = _locked_tool_call(
            connection, principal.organization_id, str(original["run_id"]),
            str(original["tool_call_id"]),
        )
        if (current["status"] not in ("executing", "unknown")
                or current["current_attempt_id"] != original["current_attempt_id"]):
            raise HTTPException(409, "Tool-call ownership changed; result was not applied.")
        row = connection.execute(
            """UPDATE sentinel_tool_calls
               SET status=%s, result=%s, external_id=%s, error=%s,
                   completed_at=CASE WHEN %s IN ('completed','failed','needs_review')
                                     THEN now() ELSE NULL END,
                   current_attempt_id=NULL, lease_expires_at=NULL
               WHERE tool_call_id=%s RETURNING *""",
            (status, Jsonb(result) if result is not None else None, external_id, error,
             status, current["tool_call_id"]),
        ).fetchone()
        add_run_event(connection, principal, current["run_id"], event_type, {
            "tool_call_id": str(current["tool_call_id"]),
            "attempt_id": str(original["current_attempt_id"]),
            "external_id": external_id,
        })
    return tool_call_view(row)


def execute_registered_tool(database, principal: Principal, run_id: str, tool_call_id: str,
                            adapter: BookingAdapter | AdapterRegistry, lease_seconds: int) -> dict:
    runtime = registry_for(adapter)
    call = claim_tool_call(database, principal, run_id, tool_call_id, lease_seconds, runtime)
    try:
        with maintain_tool_call_lease(database, principal, call, lease_seconds):
            outcome = runtime.invoke("execute", call, principal)
        external_id, result = outcome.external_id, outcome.result
        validate_payload(result, call["contract_snapshot"]["output_schema"], "Result")
    except (UncertainOutcome, EvidenceMismatch):
        return _finish_tool_execution(
            database, principal, call, "unknown", "tool_call.outcome_unknown",
            error="External result could not be confirmed.",
        )
    except HTTPException:
        return _finish_tool_execution(
            database, principal, call, "needs_review", "tool_call.invalid_result",
            error="Adapter result failed the frozen output contract.",
        )
    return _finish_tool_execution(
        database, principal, call, "completed", "tool_call.execution_completed",
        result=result, external_id=external_id,
    )


def reconcile_registered_tool(database, principal: Principal, run_id: str,
                              tool_call_id: str, adapter: BookingAdapter | AdapterRegistry,
                              lease_seconds: int) -> dict:
    runtime = registry_for(adapter)
    with database.connect() as connection:
        call, contract = _locked_tool_call(
            connection, principal.organization_id, run_id, tool_call_id
        )
        _require_supported_adapter(contract, runtime)
        if call["status"] not in ("executing", "unknown"):
            raise HTTPException(409, "Only an uncertain or interrupted call can be reconciled.")
        now = datetime.now(timezone.utc)
        if call["lease_expires_at"] is not None and call["lease_expires_at"] > now:
            raise HTTPException(409, "The tool-call worker still owns an active lease.")
        if call["status"] == "executing":
            connection.execute(
                "UPDATE sentinel_tool_calls SET status='unknown' WHERE tool_call_id=%s",
                (call["tool_call_id"],),
            )
            add_run_event(connection, principal, run_id, "tool_call.execution_interrupted", {
                "tool_call_id": str(call["tool_call_id"]),
                "expired_attempt_id": str(call["current_attempt_id"]),
            })
        attempt_id = uuid4()
        call = connection.execute(
            """UPDATE sentinel_tool_calls SET current_attempt_id=%s,
                      lease_expires_at=now() + (%s * interval '1 second')
               WHERE tool_call_id=%s RETURNING *""",
            (attempt_id, lease_seconds, call["tool_call_id"]),
        ).fetchone()
        call["contract_snapshot"] = contract
    try:
        with maintain_tool_call_lease(database, principal, call, lease_seconds):
            outcome = runtime.invoke("reconcile", call, principal)
        external_id, result = outcome.external_id, outcome.result
        validate_payload(result, contract["output_schema"], "Result")
    except (UncertainOutcome, EvidenceMismatch, HTTPException):
        return _finish_tool_execution(
            database, principal, call, "needs_review", "tool_call.reconciliation_unresolved",
            error="Reconciliation could not prove a valid result.",
        )
    return _finish_tool_execution(
        database, principal, call, "completed", "tool_call.reconciliation_completed",
        result=result, external_id=external_id,
    )
