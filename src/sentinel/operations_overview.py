"""Tenant-scoped operational counters, without arguments, contacts or tokens."""
from .security import require_roles


def operations_overview(database, principal, settings, adapters):
    require_roles("admin", "developer", "reviewer")(principal)
    org = principal.organization_id
    with database.connect() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        counts = connection.execute(
            """SELECT count(*) FILTER (WHERE status='awaiting_approval') AS awaiting_approval,
                      count(*) FILTER (WHERE status='authorized') AS ready,
                      count(*) FILTER (WHERE status='unknown') AS unknown,
                      count(*) FILTER (WHERE status='needs_review') AS needs_review,
                      count(*) FILTER (WHERE status='executing' AND lease_expires_at<=now()) AS expired_leases,
                      count(*) FILTER (WHERE status='completed') AS completed
               FROM sentinel_tool_calls WHERE organization_id=%s""", (org,),
        ).fetchone()
        runs = connection.execute("SELECT status,count(*) AS count FROM sentinel_runs WHERE organization_id=%s GROUP BY status", (org,)).fetchall()
        access = connection.execute(
            """SELECT count(*) FILTER (WHERE k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at>now())) AS active_keys,
                      count(*) FILTER (WHERE k.revoked_at IS NULL AND k.expires_at>now() AND k.expires_at<=now()+interval '7 days') AS expiring_keys,
                      COALESCE(sum(l.blocked_count),0)::bigint AS rate_limit_blocks
               FROM sentinel_api_keys k LEFT JOIN sentinel_request_limits l USING(api_key_id)
               WHERE k.organization_id=%s""", (org,),
        ).fetchone()
        captured = connection.execute("SELECT now() AS captured_at").fetchone()["captured_at"]
    return {"captured_at": captured, "tool_calls": counts, "runs": {row["status"]: row["count"] for row in runs},
            "access": access, "request_policy": {"requests": settings.requests_per_window,
                                                   "window_seconds": settings.request_window_seconds},
            "installed_adapters": [{"name": item["name"], "version": item["version"]} for item in adapters.discovery_filters()],
            "booking_circuit": adapters.booking_circuit_snapshot(),
            "boundary": "Ledger counters, not a production-readiness score. External monitoring, public user sign-in, and hosted integration checks remain open."}
