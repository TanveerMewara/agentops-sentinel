# Stage 6: native production release evidence

Stage 6 completes the automated, Docker-free local release path. It does not turn
local evidence into proof of a public multi-user production deployment. Those are
separate external activities listed at the end of this document.

## Native installation and service lifecycle

`scripts/install_check.py` verifies Python 3.11+, required imports, pinned package
consistency, bundled Node, frontend dependencies/build output, ignored local
credentials, PostgreSQL connectivity and the absence of a Docker requirement.

`scripts/local_service.py` manages the booking sandbox, Sentinel API, compiled
dashboard and worker as separately recorded processes. Each PID is paired with its
creation time so a recycled PID is never stopped. The service refuses partial or
unverified state and binds every component to loopback.

```powershell
.\.venv\Scripts\python.exe scripts\local_service.py start --demo
.\.venv\Scripts\python.exe scripts\local_service.py status
.\.venv\Scripts\python.exe scripts\local_service.py stop
```

## Capacity and connection pooling

The first concurrent test found correct results but 6.06-second p95 latency because
each API request opened fresh PostgreSQL connections. `Database` now owns a bounded
1-20 connection pool, closes it with the FastAPI lifespan and safely creates a new
pool when the same app enters a later lifespan.

The final benchmark created 80 unique run records at concurrency 8 and replayed
every request using its original idempotency key:

- 80/80 successful, zero errors, and every replay returned the original run ID;
- 25.60 write requests/second;
- 265 ms p50, 610 ms p95 and 734 ms maximum latency;
- required p95 threshold: at most 2,000 ms.

This is a bounded single-laptop result, not a distributed load claim.

## Full automated release profile

The full profile now contains 23 sequential stages: unit tests, frontend type/lint/
production build, installation readiness, migration concurrency, all PostgreSQL/API
acceptance suites, security and failure labs, capacity, native service lifecycle,
compiled pilot startup/demo replay, and backup/restore.

The 22 September 2026 report passed every stage. Evidence includes 217 unit tests,
62 security checks, 35 failure checks, all 24 migrations and a 64-table restore
with matching row counts. The report records `automated_release_ready: true` and
intentionally keeps `production_ready: false`.

## Remaining external evidence

These cannot be manufactured by code running in this workspace:

1. A connected real browser must complete interaction, responsive-layout, keyboard
   and accessibility checks. Browser discovery returned no available browser during
   this stage, although TypeScript, lint, production build and compiled HTTP startup passed.
2. A second person must install the product and complete a useful independent-agent
   workflow; our own installation diagnostic is not independent-user evidence.
3. A chosen hosted environment must run live provider trials, monitoring, scheduled
   offsite backups and restore rehearsal. The selected target remains the local
   laptop pilot, so no public deployment target or credentials were available.

Until those are supplied, Sentinel is an automated-release-ready local product and
not a verified public production service.
