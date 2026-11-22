"""Redacted run timelines built from durable events, not raw prompts or contacts."""
from fastapi import HTTPException
from .security import require_roles


def run_summaries(database, principal, limit):
    require_roles("admin", "developer", "reviewer", "worker")(principal)
    with database.connect() as connection:
        return connection.execute(
            """SELECT run_id, agent_version_id, status, steps_used, max_steps,
                      created_at, started_at, completed_at FROM sentinel_runs
               WHERE organization_id=%s ORDER BY created_at DESC, run_id LIMIT %s""",
            (principal.organization_id, limit),
        ).fetchall()


def run_timeline(database, principal, run_id):
    require_roles("admin", "developer", "reviewer", "worker")(principal)
    with database.connect() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        run = connection.execute(
            """SELECT run_id, agent_version_id, status, steps_used, max_steps,
                      created_at, started_at, completed_at FROM sentinel_runs
               WHERE run_id=%s AND organization_id=%s""", (run_id, principal.organization_id),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found.")
        events = connection.execute(
            "SELECT event_id, event_type, created_at FROM sentinel_run_events WHERE run_id=%s AND organization_id=%s ORDER BY event_id",
            (run_id, principal.organization_id),
        ).fetchall()
        models = connection.execute(
            """SELECT invocation_id, provider, model_alias, status, input_tokens,
                      output_tokens, total_tokens, duration_ms, created_at
               FROM sentinel_model_invocations WHERE run_id=%s AND organization_id=%s ORDER BY created_at, invocation_id""",
            (run_id, principal.organization_id),
        ).fetchall()
        engagement = connection.execute(
            "SELECT event_id, event_type, created_at FROM estate_engagement_events WHERE run_id=%s AND organization_id=%s ORDER BY event_id",
            (run_id, principal.organization_id),
        ).fetchall()
        retrievals = connection.execute(
            "SELECT retrieval_id, created_at FROM estate_retrieval_queries WHERE run_id=%s AND organization_id=%s ORDER BY created_at",
            (run_id, principal.organization_id),
        ).fetchall()
    timeline = [{"source": "run", "kind": row["event_type"], "at": row["created_at"], "id": str(row["event_id"])} for row in events]
    timeline += [{"source": "engagement", "kind": row["event_type"], "at": row["created_at"], "id": str(row["event_id"])} for row in engagement]
    timeline += [{"source": "retrieval", "kind": "retrieval.completed", "at": row["created_at"], "id": str(row["retrieval_id"])} for row in retrievals]
    timeline += [{"source": "model", "kind": "model." + row["status"], "at": row["created_at"], "id": str(row["invocation_id"]),
                  "tokens": row["total_tokens"], "duration_ms": row["duration_ms"]} for row in models]
    timeline.sort(key=lambda row: (row["at"], row["source"], row["id"]))
    elapsed = int((run["completed_at"] - run["started_at"]).total_seconds() * 1000) if run["completed_at"] and run["started_at"] else None
    return {"run": run, "timeline": timeline, "model_invocations": models,
            "metrics": {"model_tokens": sum(row["total_tokens"] for row in models),
                        "model_duration_ms": sum(row["duration_ms"] for row in models),
                        "run_duration_ms": elapsed, "model_calls": len(models),
                        "estimated_cost": None},
            "redaction": "Prompts, outputs, contact fields, arguments, and event payloads omitted.",
            "telemetry_source": "postgresql_event_ledger"}
