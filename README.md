# AgentOps Sentinel

AgentOps Sentinel is an execution, reliability, evaluation, observability, and
security platform for AI agents across domains. EstateFlow AI is an optional
example integration, alongside the independent support-triage example. Connecting
your agent does not require leads, property listings, calendars or CRM records.

## Live deployment

- **Dashboard:** https://agentops-sentinel-blush.vercel.app (Vercel)
- **API health:** https://agentops-sentinel-api.onrender.com/health (Render, Singapore)
- **Database:** Neon Postgres 17 (Singapore)

It runs on free tiers: the API sleeps after 15 minutes without traffic, so the first
request after a pause takes about a minute. Connecting the dashboard to the API
requires an API key. Setup, free-tier notes and the always-on upgrade path are in
[docs/deploy-vercel.md](docs/deploy-vercel.md).

The dashboard opens on a general agent workspace with a cinematic featured-agent
area and horizontally scrollable fleet, recent-activity and review rows. Cards
use live registry data; selection opens configuration controls. No fictional
safety scores are displayed. The workspace supports agent registration, immutable
versions, JSON run-record creation, saved runs, tool contracts, evaluations and
access controls. EstateFlow screens are under **Example integrations**. Creating
a run record does not execute an arbitrary agent; your integration controls
execution through the API/client and supported adapters.

The repository currently contains a verified **durable execution core**, plus the
earlier learning experiments. It is not yet the complete public product described
in [product scope](docs/product-scope.md).

The Docker-free automated local release profile now passes, including capacity,
process lifecycle and database recovery. Start the compiled product with
`python scripts/local_service.py start --demo`; inspect it with `status` and stop it
with `stop`. See [Stage 6 release](docs/stage-6-release.md) for measured evidence and
the external checks still required for a public production claim.

The repository also includes a reproducible benchmark for structured failure
diagnosis, paired monitoring overhead, P50/P95/P99 latency, controlled reliability,
concurrent local load, synthetic-provider token/cost analysis, automated test
counts, and backend coverage. Run
`.\.venv\Scripts\python.exe scripts\run_benchmarks.py` after installing
`requirements-dev.txt`. Methodology, formulas, and evidence boundaries are in
[BENCHMARKS.md](BENCHMARKS.md); generated evidence is written to `reports/`.

## Working core

- Product operations for browser-member onboarding, CSRF-protected sessions,
  privacy-minimal alerts, passed-gate deployment authorization and persistent
  failure/security lab campaigns. The live control center also configures generic
  tools/grants and encrypted model providers. See
  [Stage 5 product operations](docs/stage-5-product-operations.md).

- Production-shaped OTLP/HTTP receipt for traces, metrics and logs in JSON or
  Protobuf with optional gzip, run correlation, aggregate latency/token evidence,
  versioned rate-card cost estimates, completeness gaps and retention/deletion
  controls. Raw logs and arbitrary metric attributes are never stored. See
  [Stage 3 telemetry](docs/stage-3-telemetry.md) and
  [OpenTelemetry tracing](docs/opentelemetry-tracing.md).

- LangChain Core/LangGraph callback tracing with structural spans and optional
  provider-reported token usage while excluding prompts, arguments, documents,
  results and exception text; see [framework tracing](docs/langchain-langgraph-tracing.md).

- OpenAI Agents SDK tracing through a custom processor, plus runnable plain-Python,
  LangGraph and Agents SDK examples with success, failure and interruption paths;
  see [Stage 2 agent integrations](docs/stage-2-agent-integrations.md).

- Deterministic external-trajectory checks for required, ordered and forbidden
  operations, reported status, duration, span failures and reported model usage,
  with privacy-safe v4 reports; see [trajectory evaluations](docs/trajectory-evaluations.md).

- Calibrated semantic evaluator v5 with declared held-out/category coverage,
  weighted cases, strict non-stored structured judge responses, immutable human
  labels, repeated-run uncertainty, prompt/model/retrieval variant comparison,
  online sampling and CI-verifiable release gates; see
  [Stage 4 evaluations](docs/stage-4-evaluations.md).

- Deterministic JSON-reference and bounded schema checks of external outputs,
  with privacy-safe versioned reports; see [output evaluations](docs/output-evaluations.md).

- Immutable external-agent trace/output ingestion, a synchronous Python recorder,
  SDK submission/read calls and a dashboard evidence inspector; reports remain
  caller-provided observations, separate from governed execution proof. See the
  [external evidence guide](docs/external-agent-traces.md).

- Domain-independent saved-run evaluation for terminal status, steps, recorded
  model budgets, tool-call completion/failure/uncertainty and exact consumed
  approvals; EstateFlow-specific rules use a conditional example collector
- Neutral external-agent Python-client defaults and rejection of external runs
  by built-in EstateFlow workflow endpoints; existing frozen versions are preserved
- Value-free tool/model validation diagnostics and a repeatable local security lab
  with explicit coverage gaps; see the [threat model](docs/threat-model.md)
- Native viewing-calendar dashboard with live availability, offer/withdrawal controls,
  current reservation records, idempotent reservation/cancellation proposals,
  exact-action review, execution/recovery controls, and role-aware access
- Automatic lead-bound native viewing workflow with frozen buyer qualification,
  exact-slot planning, verified reservation outcomes, internal CRM/follow-up linkage,
  and cancellation that invalidates unsent confirmation drafts
- PostgreSQL-backed operations and append-only lifecycle events
- Organization-scoped API keys with admin, developer, reviewer, and worker roles
- Database-enforced idempotency within each organization
- Human approval bound to a canonical hash of exact action details
- Approval expiry, revocation, rejection, and one-time consumption
- Background worker dispatch through the authenticated API
- Automatic recovery scanning for uncertain and lease-expired executions
- Fenced reconciliation leases that stop competing recovery workers from committing twice
- Lease heartbeats for long external execution and reconciliation calls
- Bounded retry backoff with jitter for transient worker connectivity failures
- Service-specific booking adapter with exact receipt validation
- Explicit `unknown` and `needs_review` outcomes
- Execution leases that prevent immediate reconciliation of active work
- PostgreSQL schema migrations
- Persistent fictional booking service used as the first external integration
- Organization-scoped agent and versioned tool registry
- Strict JSON tool contracts, risk policy, agent grants, and per-run call limits
- Append-only registry audit events
- Immutable agent versions and idempotent, organization-scoped run records
- Frozen per-run tool contracts, atomic call reservations, and enforced step/call budgets
- JSON Schema validation of tool arguments and results with append-only run events
- Exact, expiring human approval for high-risk run tool calls
- Whitelisted booking-adapter dispatch with one-time approval consumption
- Fenced tool-call execution leases and evidence-only crash recovery
- Provider-neutral model decision contract with a deterministic local EstateFlow provider
- PostgreSQL-checkpointed LangGraph workflow with approval pause and restart-safe resume
- OpenAI Responses provider adapter with strict Structured Outputs and bounded timeouts
- Encrypted provider credentials, safe key hints, deterministic fallback, and usage ledger
- Versioned EstateFlow property ingestion with atomic batches and idempotent replay
- PostgreSQL full-text/trigram retrieval with filters, source evidence, and query audit records
- EstateFlow graph recommendations with frozen per-run evidence and no-match stopping
- Dashboard property search with business filters and source/version citations
- Versioned property embeddings, exact array cosine search, and optional pgvector path
- Reproducible synthetic retrieval benchmark with explicit real-vector opt-in
- Encrypted lead intake with transparent qualification reasons and immutable
  requirements history
- Human-review queue and reviewer resolution, with lead-bound booking safeguards
- Dashboard lead form, live queue, and review routing
- Internal CRM projection and encrypted follow-up drafts after confirmed bookings
- Reviewer-only follow-up approval and a live customer-engagement dashboard queue

## Local development on Windows

For the selected laptop pilot, see [one-command local launch](docs/local-pilot.md).
Run `.\.venv\Scripts\python.exe scripts\release_check.py --profile full`, then
`.\.venv\Scripts\python.exe scripts\pilot.py --demo` to start all local components
with an explicitly fictional reference configuration.
Docker is excluded. Bookings remain fictional and emails remain internal drafts.

Requirements: Python 3.11+, PowerShell, and the official PostgreSQL 17.11 archive
described in [native PostgreSQL setup](docs/local-postgresql.md). The current
machine is already initialized.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\dev.py setup
```

Start three terminals:

```powershell
# Terminal 1: fictional external booking service
.\.venv\Scripts\python.exe scripts\dev.py serve-booking

# Terminal 2: Sentinel API at http://127.0.0.1:8000/docs
.\.venv\Scripts\python.exe scripts\dev.py serve-api

# Terminal 3: background worker
.\.venv\Scripts\python.exe scripts\dev.py serve-worker
```

Start the operations dashboard in a fourth terminal. The repository includes an
ignored, project-local Node.js runtime, so no system-wide Node installation is needed:

```powershell
cd web
$nodeRoot = (Resolve-Path "..\.local\node-v24.16.0-win-x64").Path
$env:Path = "$nodeRoot;$env:Path"
& "$nodeRoot\npm.cmd" install
& "$nodeRoot\npm.cmd" run dev
```

Open `http://localhost:3000`, choose **Connect API**, and use a development key
from `scripts/dev.py show-keys`. The browser keeps the key in memory for the current
tab only. Set `SENTINEL_ALLOWED_ORIGINS` to a comma-separated allowlist when the
dashboard is served from another origin.

Use a developer key to import listings through `/v1/properties` or
`/v1/properties/batch`, then search them in the dashboard. To attach the same search
to a durable EstateFlow run, include `property_query` and optional
`property_filters` inside the run's `input` alongside `customer` and `slot`.
The workflow response includes the frozen recommendations and retrieval ID;
no match stops before booking approval.

Create a lead with `POST /v1/leads`. A complete lead needs contact email, outreach
consent, preferred city, maximum budget, and a known timeline to be qualified;
later timelines route to nurture. A run may pass `lead_id` and `slot` in its input
instead of a customer name. The workflow uses the lead's name and property
requirements, then rechecks its qualification before booking. `/v1/leads/{lead_id}/handoff`
routes a lead to human review, and a reviewer can use
`/v1/leads/{lead_id}/resolve-review` to return it to the stated rules. The lead
dashboard works against the same authenticated API. Contact name and email are
encrypted in the lead table; booking tool arguments still contain the customer name,
so run-level PII redaction remains future work.

Confirmed lead bookings update `/v1/crm/contacts` and create an encrypted email
draft at `/v1/followups`. Reviewers approve drafts through
`/v1/followups/{draft_id}/approve`. This CRM is an internal database projection,
not an external CRM integration, and approved drafts are not sent. The current
booking adapter supports property-bound contracts with a listing ID and immutable
version. See the booking and review documentation for exact approvals and
receipt checks.

Vector search uses the `strategy: "vector"` option and an embedding model alias
(default `estate_embeddings`). An admin configures that alias with model ID
`text-embedding-3-small` through `/v1/model-providers/openai`, then calls
`/v1/properties/embeddings/backfill`. Each call embeds at most ten current active
listings. The native development database supports exact array cosine search up to
500 matching listings. [pgvector's official setup](https://github.com/pgvector/pgvector/blob/master/README.md#installation)
is required before `scripts/enable_pgvector.py` can enable the pgvector branch.
This machine's Docker engine and pgvector extension are currently unavailable.

Display development API keys when testing the interactive API:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py show-keys
```

Credentials and database files live under ignored `.local/`. They must not be shared.
Long-running adapters can tune the ownership window with
`SENTINEL_EXECUTION_LEASE_SECONDS` (3–3600 seconds); the API renews the lease while
the external call is active.

## Verification

Website delivery deduplication and the dashboard-to-worker viewing entry flow are
described in [website enquiries](docs/website-enquiries.md).
Property-bound actions, editable drafts, revision-specific approvals, and separate
run outcomes are described in [booking and review](docs/property-booking-review.md).
Versioned saved-run evaluations, report gates, comparisons, and redacted timelines
are described in [evaluations and timelines](docs/evaluations-and-timelines.md).
Native service commands and backup/restore checks are in the
[release runbook](docs/native-release-runbook.md).
Key administration and the independent Python agent client are in
[access and client integration](docs/access-and-client.md).
Read-only AI-tool access is in [MCP integration](docs/mcp-integration.md).
Response protections and real-socket checks are in [API security](docs/api-security.md).
Deployment-installed tool adapters, shared request limits, and the Operations
pulse panel are in [adapters and operations](docs/adapters-and-operations.md).
Operations pulse also displays the installed booking guard's dispatch state and
cooldown, without probing the provider or exposing shared failure history.
The [native viewing calendar](docs/native-calendar.md) adds offered slots,
overlap-safe approved reservations and cancellations, and durable decision receipts.
Its automatic workflow is available from **Leads → Arrange viewing → Native viewing
calendar**. Enable its dedicated agent and select an offered slot; the original
reference booking configuration remains separately selectable.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests\acceptance_adapters_limits.py
.\.venv\Scripts\python.exe tests\acceptance_calendar.py
.\.venv\Scripts\python.exe scripts\security_lab.py
.\.venv\Scripts\python.exe tests\acceptance_migrations.py
.\.venv\Scripts\python.exe scripts\native_postgres.py check
.\.venv\Scripts\python.exe tests\integration_api.py
.\.venv\Scripts\python.exe tests\acceptance_enquiries.py
.\.venv\Scripts\python.exe tests\acceptance_evaluations.py
.\.venv\Scripts\python.exe tests\acceptance_access_client.py
.\.venv\Scripts\python.exe tests\acceptance_external_traces.py
.\.venv\Scripts\python.exe tests\acceptance_telemetry.py
.\.venv\Scripts\python.exe tests\acceptance_advanced_evaluations.py
.\.venv\Scripts\python.exe scripts\benchmark_retrieval.py
.\.venv\Scripts\python.exe scripts\failure_lab.py
.\.venv\Scripts\python.exe scripts\run_benchmarks.py
```

The tests use fictional local data. Database management may need the same Windows
permission context that initialized PostgreSQL.

The [local failure lab](docs/failure-lab.md) exercises committed bookings with
lost replies, temporary outages, and invalid evidence over real loopback sockets.
It records a private local report and never calls real providers.

## Repository map

- `src/sentinel/`: integrated application core
- `web/`: responsive operations dashboard and live API controls
- `src/sentinel/migrations/`: ordered PostgreSQL schema changes
- `scripts/dev.py`: local bootstrap and service launcher
- `tests/integration_api.py`: real API and PostgreSQL acceptance path
- `lessons/`: preserved teaching experiments and fictional booking service
- `docs/architecture-flowcharts.md`: full target architecture
- `docs/curriculum.md`: delivery plan and release criteria
- `docs/project-status.md`: current completed and remaining product milestones

## Current boundary

This is an internal development release. The durable workflow, property-bound
fictional booking, internal CRM/draft review, saved-run rules evaluation, redacted
ledger timelines, native backup rehearsal, service-key administration, Python
client, and read-only stdio MCP are implemented and checked locally.
Live-provider/pgvector validation, real calendar/CRM/email integrations, external
adapter validation, broader OpenTelemetry operations, evaluation/security labs, remote MCP/OAuth,
production user identity, deployment, offsite backups, and outside-user onboarding
remain open. See project status for the detailed scope and evidence boundaries.
Public production readiness will be claimed only after the release criteria in the
curriculum are exercised.
