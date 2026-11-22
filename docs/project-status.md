# AgentOps Sentinel project status

Updated: 21 September 2026

The cinematic agent dashboard is retained. Its shared styles now consistently
use black/charcoal, white/neutral text and red-family accents, including example
panels, forms and dialogs. Outcome labels remain explicit; no workflow state or
authorization behavior changed with the palette.

## Current position

Latest Stage 6 update: the Docker-free local release has installation diagnostics,
a native four-component service manager, bounded PostgreSQL connection pooling and
a measured concurrent-write gate. The final 23-stage full profile passed. Capacity
was 80/80 writes with exact replay, 25.60 requests/second and 610 ms p95 at
concurrency 8. The current evidence includes 217 unit tests, 62 security checks,
35 failure checks, 24 migrations and a verified 64-table restore. The automated
local release is complete. A real connected-browser pass, independent outside-user
pilot and chosen hosted/offsite deployment remain necessary before calling it a
verified public production service. See [Stage 6 release](stage-6-release.md).

Latest Stage 5 update: migration 024 adds browser members/invitations/sessions,
pre-authentication limits, alert policies/inbox, deployment environments/records
and persistent lab campaigns. The dashboard now has a live product operations
control center for generic tool grants, encrypted model providers, alert review,
team onboarding, release evidence and bounded labs. Its connection dialog supports
service keys and CSRF-protected browser member sessions. Deployment records require
a passed immutable release gate. The Python client exposes alerts, deployments and
lab campaigns. Real PostgreSQL acceptance passes the complete Stage 5 workflow.
See [Stage 5 product operations](stage-5-product-operations.md).

Latest Stage 4 update: evaluation datasets now support category/split/weight fields
and enforce declared coverage. Semantic evaluator v5 grades finalized external
outputs through a strict provider boundary with structured responses, `store=False`,
bounded repetitions and privacy-safe reports. Immutable human labels produce frozen
calibration reports with mean absolute error and label agreement. Multi-experiment
analysis reports mean pass rate, variation, descriptive intervals, categories and
prompt/model/retrieval variants. Immutable release gates require configured quality,
stability, held-out data, calibration for semantic reports and optional baseline
regression tolerance. Deterministic tenant-scoped online sampling enforces a daily
limit and stable replay. Migration 023 adds labels, calibrations, gates, sampling
policy and sample records. Real PostgreSQL acceptance passes the full Stage 4 flow
with three held-out categories, two repeated experiments, three human labels, a
passing calibration and release gate, CI validation and online-sample replay. The
live OpenAI adapter follows the current Responses structured-output contract, but a
live call was not run because no evaluation credential is configured; acceptance
uses a deterministic implementation of the same judge boundary. No dashboard UI
was changed. See
[Stage 4 evaluations](stage-4-evaluations.md).
The current regression has 217 passing unit tests. Competing startup applied all
24 migrations exactly once, the broad authenticated API/restart/recovery acceptance
passed, and the backup rehearsal restored all 64 public tables with matching row
counts and readable encrypted lead data. The Vinext production build, TypeScript
check and changed-file ESLint check pass.

Latest Stage 3 update: authenticated OTLP/HTTP now accepts trace, metric and log
exports at the standard paths using JSON or binary Protobuf, with identity or gzip
content encoding and matching OTLP success responses. The receiver enforces a
1 MiB transport limit, a 4 MiB decoded limit and 10,000-item metric/log bounds.
It stores privacy-minimal aggregates: token totals, model/tool/retrieval latency,
severity counts and trace-correlation counts; it never stores raw metric payloads,
arbitrary attributes or log bodies. Organization rate cards are append-versioned,
and cost is calculated only when token points provide an explicit
`sentinel.pricing.key`. Policies define required signals, token/cost requirements
and 1–365 day retention. Run summaries fail closed with explicit gaps. Admin purge
and run deletion remove expiring normalized telemetry while preserving finalized
immutable external evidence. Migration 022 adds three telemetry tables and pending
trace expiry. All 203 unit tests and the real PostgreSQL Stage 3 acceptance pass.
Acceptance covers Protobuf traces/metrics, gzipped JSON logs, replay, versioned
costs, privacy, completeness, role denial, purge and deletion. No dashboard UI was
changed. Alert delivery, live outside exporters, monitoring-overhead measurement
and deployment scheduling remain open. See [Stage 3 telemetry](stage-3-telemetry.md).

Latest Stage 2 update: three runnable external-agent paths now use Sentinel's public
integration boundary: plain Python support triage, a compiled LangGraph, and the
OpenAI Agents SDK. The SDK integration uses a custom privacy-minimal tracing
processor and pins `openai-agents==0.22.3`. Local tests exercise an actual Agents SDK
`Agent` and `Runner` with its deterministic model, plus success, failure and
interruption paths for both framework examples. Real PostgreSQL acceptance now
finalizes support, code-analysis, LangGraph, OpenAI Agents SDK and OTLP traces and
runs one passing `agent_rules_v4` experiment across all five domains. No governed
tool or model ledger is fabricated. Prompts, responses, model names, tool
arguments/results and exception text are excluded. A live OpenAI call was not run
because `OPENAI_API_KEY` is absent; the documented live command requires an explicit
credential and model. See [Stage 2 agent integrations](stage-2-agent-integrations.md).
The complete 197-test unit suite, access/client acceptance, five-domain external
trace acceptance, MCP subprocess acceptance, API recovery and 46-table restore all
pass after this change. A new consolidated native-profile attempt passed through
the expanded external-trace stage, then the laptop paused and detached the following
stage; a second attempt encountered the same machine pause during access/client.
That access/client command passed immediately when rerun directly. Therefore the
earlier complete native profile remains the latest single-run baseline, while the
post-Stage-2 evidence is a set of current passing commands rather than a newly
completed one-process profile. No timeout or assertion was weakened.

Latest receiver update: authenticated OTLP/HTTP JSON exporters can send a standard
`ExportTraceServiceRequest` body to `/v1/traces` with Sentinel API-key, run-ID and
optional trace-selection headers. Sentinel stores immutable privacy-filtered pending
evidence and returns the standard empty JSON success body. Pending data remains
unavailable to normal trace reads/evaluations until `finalize_otlp_trace` attaches a
sanitized output and reported status. This prevents missing output from being treated
as `{}`. Migration 021 adds the tenant/run-bound pending table. Competing startup
checks applied all 21 migrations exactly once. Real PostgreSQL acceptance covers
role and tenant denial, concurrent receipt/finalization replay, pre-finalization 404,
conflicts, sensitive-attribute exclusion, malformed/oversized requests and unchanged
governed ledgers. The complete suite passes all 197 unit tests. Backup/restore
rehearsal passed across all 46 public tables with matching counts and readable
encrypted lead data. No UI change was made. This paragraph records the earlier
Stage 2 receiver state; Stage 3 above supersedes its JSON-only limitation. See
[OpenTelemetry tracing](opentelemetry-tracing.md).

The complete native release profile passed on 21 September 2026 (run
`5000f4808e744af492861930ea124a1a`). All 11 required stages passed: unit,
migration concurrency, adapter limits, native calendar, website enquiries,
access/client security, evaluations, external traces, stdio MCP, API recovery and
backup/restore. During this verification, the operations listing was corrected to
return newest records first; a long-lived database with more than 100 operations had
previously hidden newly created operations behind the endpoint limit. The API
recovery suite now also preserves an HTTP status when an unhandled server error has
a non-JSON body, without writing that body to release logs. This evidence establishes
the current Docker-free local release baseline. It does not satisfy the external
trials, identity, hosted operations, load testing or independent-pilot requirements
for public production readiness.

Preceding framework-neutral update: `otlp_json_to_external_trace` converts one trace
from a standard OTLP/JSON export into validated Sentinel evidence. It supports
multi-trace selection, exact nanosecond hierarchy validation, bounded scanning,
OpenTelemetry GenAI operation/token attributes and common OpenInference kinds.
Resources, scope details, events, links, status messages and all content-bearing
attributes are discarded. Unit tests cover mapping, usage, status, privacy, tree
rules and malformed data. Real PostgreSQL acceptance converts and submits an OTLP
trace and verifies sensitive source attributes are absent from Sentinel evidence.
The expanded complete suite passes all 187 unit tests.
This is a local converter, not a managed OTLP receiver or proof of telemetry
completeness. No UI, database migration or external dependency changed. See
[OpenTelemetry tracing](opentelemetry-tracing.md).

Preceding framework-integration update: `SentinelLangChainCallback` now converts
LangChain Core callbacks, including a real compiled LangGraph invocation, into
bounded Sentinel external evidence. It records normalized operation names,
hierarchy, timing, status and available provider-reported token totals. It ignores
prompts/messages, chain inputs/outputs, tool arguments/results, retrieved documents,
exception text, tags and metadata. Direct adapter tests and an actual LangGraph
integration test pass. The complete suite passes all 183 unit tests, and real
PostgreSQL external-trace acceptance now submits callback evidence from a compiled
LangGraph execution through the API. `langchain-core` is now an explicit pinned
dependency rather than only a transitive LangGraph dependency. No UI or database migration changed.
This is in-process caller-reported instrumentation, not proof of complete capture or
authorization. Additional framework exporters and real outside-agent trials remain
open. See [LangChain/LangGraph tracing](langchain-langgraph-tracing.md).

Preceding trajectory update: deterministic trajectory evaluation now checks required,
ordered and forbidden reported span names, external reported status, duration,
span/failure limits, reported model-token budgets and reported usage completeness.
Missing trace evidence fails closed. Reports contain boolean verdicts, aggregate
reported metrics and definition hashes while omitting configured operation names.
Trajectory and mixed output/trajectory datasets use `agent_rules_v4`; output-only
datasets retain v3, ledger-only datasets retain v2, and historical definitions and
reports replay unchanged. All 178 unit tests and the real PostgreSQL evaluation
acceptance passed, including immutable versions, concurrent frozen replay, tenant
isolation, privacy-safe reports, missing-evidence failure and v4 gate exits. The
native PostgreSQL behavioral checks passed, but their final server-stop cleanup
could not complete because the existing local preview retained connections. No
database migration or UI change was added. The preceding restore evidence remains
unchanged, and no new full 15-stage profile, browser QA or live external-agent trial
is claimed. Evidence remains caller-reported; semantic judging, calibrated scoring,
supported framework exporters, representative data, example-free bootstrap,
capacity testing and operational validation remain open. See
[trajectory evaluations](trajectory-evaluations.md).

Preceding output-evaluation update: `output_equals` checks JSON references and
`output_schema` checks bounded structural contracts against finalized external
traces. Missing output fails a configured requirement. Matching preserves object
keys, strings and array order, compares numbers by value and distinguishes
booleans from numbers. Schema references, regex, formats and combinators are
rejected. Reports omit raw output, references, schema keys and validation errors,
and retain trace provenance plus rule-definition hashes. This checks configured
requirements, not prose truth, safety or approval of external activity.
Output-only datasets use `agent_rules_v3`; ledger-only datasets retain
v2, old definition hashes/replays are preserved and exports support all versions.
The dashboard has optional reference/schema controls and explanatory report text;
trace inspection now scrolls into view, and timeline labels identify governed
model usage. All 168 unit tests, real PostgreSQL evaluation acceptance, standalone
TypeScript checking and targeted UI lint passed. Native acceptance includes
passing, wrong-answer and missing-output reports, immutable dataset versions,
frozen replay, tenant isolation, privacy-safe diagnostics and CLI gate exits.
The final production frontend build passed. The compiled preview was restarted
without demo setup and with automatic dispatch paused; readiness-gated API health
and dashboard checks returned HTTP 200 on ports 8020/3020. Live Python SDK reads
confirmed v3 reports expose boolean output verdicts and omit raw output facts.
No migration
was added; the preceding 45-table restore evidence remains unchanged. No new full
15-stage release-profile or browser interaction pass is claimed. Semantic
evaluators, calibrated judges, supported framework exporters, real AI
trials, example-free bootstrap, browser QA and operational validation remain open.
See [output evaluations](output-evaluations.md).

Preceding standalone update: finalized external-agent traces and JSON outputs can
be ingested through tenant-scoped API/SDK calls and inspected/imported from saved
runs in the dashboard. A synchronous Python recorder captures nested operation
names, timing and explicitly supplied model usage. Evidence is immutable per run
with canonical replay checks, value-free audit events and output opt-in on reads.
Reported activity is explicitly caller-provided; it does not execute actions,
consume approvals, mutate governed tool/model budgets or change run status.
Unknown usage remains visible as incomplete coverage. Transport is bounded before
parsing and normalized evidence is bounded to 64 KiB/100 spans.
All 159 final unit tests and real PostgreSQL external-trace acceptance passed.
Acceptance uses synthetic support/code-analysis fixtures, not live AI trials.
The first acceptance attempt had an incorrect test-fixture organization column;
the fixture was corrected and the complete rerun passed. Standalone TypeScript
checking, targeted lint and the final production frontend build passed. The
restore rehearsal passed for all 45 public tables with matching snapshot counts.
The CSS palette check found no colors outside neutral/red families. Browser
interaction/visual QA remains open; compilation is not visual verification.
The compiled preview was restarted without demo setup and with automatic dispatch
paused. Readiness-gated API health (8020) and dashboard (3020) checks returned
HTTP 200. Migration 020 adds the external-trace table. Framework-specific
adapters, real external AI trials, output correctness evaluation, browser QA and
operational validation remain unfinished. The full release plan now includes
15 stages; no new full-profile run has been claimed for this update.

Preceding backend update: generic saved-run evaluations now collect only Sentinel
ledger facts, including completed/failed/uncertain tool calls, total call budgets
and exact consumed approval checks. EstateFlow business facts are collected only
for explicitly requested legacy rules through an isolated integration module.
New reports use `agent_rules_v2`; old exports remain supported, and comparison
requires matching dataset and evaluator versions. The Python client defaults to
external-agent metadata. Built-in workflow endpoints reject explicit external
runs/unmarked external aliases while preserving legacy example behavior.
All 151 final unit tests, real PostgreSQL evaluation acceptance and access/client
acceptance passed. Native calendar/workflow regression also passed on the serial
rerun, including competing bookings, expiry, cancellation and lost-reply recovery.
No migration was
added. This does not implement automatic external tracing, correctness judging,
configurable runner plugins or an example-free bootstrap.
The final suite and evaluation acceptance include exact old-format dataset
serialization/replay, preserving definition hashes when new rules are unused.
One calendar attempt timed out opening a PostgreSQL connection during retrieval.
A subsequent activity check found no blocked queries; the cause was not isolated.
The serial rerun passed, and no assertion/timeout/TLS check was relaxed. The
initial connection timeout remains a recorded reliability issue with no confirmed cause.
After the backend acceptance checks, the compiled preview was restarted without
demo setup and with automatic dispatch paused. Final readiness-gated checks
returned HTTP 200 for API health on port 8020 and the dashboard on port 3020.

Preceding UI update: the agent dashboard now uses a Netflix-inspired library layout
with a featured agent, horizontal fleet/recent-activity/review rows, identity
artwork drawn with CSS and existing icons, card selection into configuration,
scroll controls, visible keyboard focus and reduced-motion support. Registry and
run data remain live; attention rows describe failed/review-required runs in the
latest 100 loaded records, not safety scores. The saved-run list shows at most
20 search matches while searching all loaded records. Configuration forms are
collapsible. The disconnected view contains no fabricated agents or results.
Final TypeScript checking, targeted lint and the production frontend build passed.
That UI-only update changed no backend/database behavior; browser QA remains open.
The compiled cinematic preview was restarted with automatic worker dispatch
paused. After the launcher reported dashboard readiness, API health on port 8020
and the dashboard on port 3020 returned HTTP 200. No browser is connected for
interaction QA; this is compilation and live HTTP evidence, not visual verification.

The latest product direction makes Sentinel a standalone platform for supported
agents across domains. EstateFlow is an optional example, not required product
scope. The dashboard now opens on general agent/version/run/tool management;
EstateFlow panels are mounted only when its example section is selected. Generic
evaluation defaults and budget inputs replace the EstateFlow-first presentation.
Backend bootstrap still installs example components/tables, and configurable
runner/facts-provider registration remains unfinished. See
[standalone platform](standalone-platform.md) and the updated
[release backlog](release-backlog.md). TypeScript checking, targeted ESLint for
the three changed client components, and the full production frontend build passed
for this update. Lint initially rejected an unescaped apostrophe; the text was
corrected and the rerun passed. Those UI changes preceded the backend update above. The
14-stage integrated scheduling report below is a preceding baseline, not a new
full-profile pass for this dashboard update. Browser interaction QA remains open.
The compiled preview was restarted without requesting EstateFlow demo setup,
with automatic worker dispatch paused. Live identity and agent/tool/run reads
passed for administrator, developer and reviewer roles; the dashboard returned
HTTP 200 on port 3020. Initial reachability checks preceded service readiness and
received connection refusal; the final checks passed after startup completed.
No browser interaction or new write-flow acceptance was performed for this UI
update; existing API acceptance remains preceding evidence.

The first launch is a local laptop pilot, without Docker. A compiled-pilot launcher,
optional fictional reference configuration, working panel navigation, and a
sequential release-check command are implemented. The full check command records
each passing, failing, or unexecuted stage in ignored `.local/release-checks/latest.json`.

The earlier 90% estimate was too optimistic for the full agreed scope and has been
withdrawn. There is no measured overall completion percentage. Local pilot checks
and completion of the broader platform are separate milestones. Real provider
integrations, broader telemetry/evaluation/security capabilities, user identity,
hosting, load testing, and independent pilot validation remain unfinished.

## Implemented and verified

- Automatic lead-bound native scheduling is implemented: the lead launcher can
  enable its dedicated native agent and select an offered property slot. The graph
  freezes lead and property versions, plans the exact native action, pauses for
  reviewer approval, and creates internal CRM/follow-up outcomes only after a
  confirmed reservation. Direct worker execution also rechecks qualification and
  consent. Unavailable slots stop without a booking; cancellation moves the matching
  CRM record to human review and invalidates unsent drafts. Native acceptance now
  covers competing buyers, approval rejection/expiry, stale leads/listings/slots,
  cancellation before engagement, and lost-response recovery after app recreation.
  All 14 full-release stages passed for this update; the final 139-test unit rerun
  and expanded 58-check security lab also passed. External calendar/CRM/email
  connections remain open.
- Tool/model validation diagnostics now omit rejected values and arbitrary nested
  field names. New scripted hostile-decision and report-privacy tests passed in the
  full 128-test unit run. The local security lab passed 47 checks across seven groups
  and saved an atomic, payload-free report in `.local/security-lab/latest.json`.
  Skips/expected failures/empty groups remain partial; errors/failures remain failing.
  The [threat model](threat-model.md) states boundaries and unfinished security work.
  This is scripted boundary regression evidence, not a prompt-injection detector,
  hosted-model attack success rate, security score, or production readiness claim.
  Expanded native calendar acceptance also passed the real tool-reservation route:
  rejected canary field names/values were absent from its 422 response, and invalid
  arguments created no tool-call ledger entry. Existing native approval, booking,
  cancellation, recovery, closure, and tenant-isolation cases passed unchanged.
- Native Viewing calendar dashboard: live offers/availability and current reservation
  records, administrator/developer offer and withdrawal controls, reviewer read-only
  listing access, local-time inputs converted to UTC, and connection-bound display state.
  Counts are explicitly limited to loaded records. The panel now submits idempotent
  reservation/cancellation proposals, exact-action approval/rejection/revocation,
  execution, receipt recovery, and single-action manual desk closure. Worker access
  is queue-only; generic tool-reservation permissions remain unchanged.
  TypeScript, targeted lint, and the production frontend build passed. Browser
  automation timed out during connection, so visual/interaction QA remains open.
  The native calendar acceptance check passed again. The restarted compiled pilot
  served the calendar markup, and authenticated developer/reviewer reads plus worker
  denial passed live HTTP checks. These checks do not replace browser interaction QA.
- Compiled local pilot startup with real health endpoints and authenticated identity
- Optional fictional agent/version, property-bound tool grant, and metro listing;
  repeated demo configuration reuses the same resource IDs
- Worker and Python-client redirect blocking; worker requires HTTPS outside loopback
- Dashboard panel navigation, separate pending/active filters, and search shortcut;
  dashboard API requests reject redirects and cleartext external base URLs
- Sequential release-check profiles with atomic reports and fail-stop behavior;
  report success is local evidence and never claims production readiness

- PostgreSQL operation ledger, migrations, and append-only lifecycle events
- Organization API keys, roles, tenant isolation, and permission tests
- Idempotent operation creation and exact-action approvals
- Approval expiry, rejection, revocation, and one-time consumption
- Fenced execution and reconciliation attempts
- Lease-expiry recovery through read-only external evidence lookup
- Lease heartbeats for long execution and reconciliation calls
- Worker transient-failure backoff with jitter
- Fictional persistent booking adapter and strict receipt validation
- Versioned agent and tool registry with strict JSON contracts
- High-risk approval policy, agent-tool grants, and per-run call limits
- Registry audit events and database-enforced cross-tenant grant protection
- Immutable agent configurations and idempotent versioned runs
- Frozen run-level tool contracts and permission limits
- Atomic step and per-tool call-budget enforcement
- Draft 2020-12 argument/result validation and append-only run events
- Exact, expiring approval for high-risk tool calls with one-time consumption
- Whitelisted booking dispatch with fenced leases, heartbeats, and evidence-only recovery
- Background-worker discovery for authorized and interrupted registered-tool calls
- Provider-neutral model gateway with a deterministic local provider
- PostgreSQL-backed LangGraph checkpoints and approval interrupts
- API-restart workflow resumption without duplicate planning or tool reservation
- Reviewer-rejection branch with consistent run cancellation
- OpenAI Responses adapter with strict structured output and bounded timeouts
- Encrypted organization-scoped provider credentials and admin-only configuration
- Token, latency, provider-response, and fallback invocation accounting
- Validated deterministic fallback for hosted-provider failures
- Organization-scoped property records with immutable version history
- Atomic, idempotent property batch ingestion
- Full-text/trigram property ranking with business filters
- Persistent retrieval evidence with source URI and property-version citations
- Workflow recommendations with frozen per-run retrieval snapshots and a no-match exit
- Restart-safe retrieval replay and versioned listing reverts
- Responsive operations dashboard with live API connection and recovery controls
- Dashboard property search with structured filters, listing-version citations,
  matched-term evidence, and safe source links
- Social preview metadata and production frontend build
- Versioned property embeddings, admin backfill, and exact cosine retrieval
- Embedding model/version citations, coverage checks, invocation accounting, and
  frozen vector-search snapshots in workflow runs
- Optional pgvector migration and deployment definition, plus a labeled synthetic
  retrieval benchmark with a measured lexical baseline
- Tenant-scoped lead intake, explicit qualification reasons, and encrypted contact
  fields with requirements-only immutable version history
- Human-review request and resolution with an auditable lead queue in the dashboard
- Lead-bound booking that uses verified buyer requirements and stops when the lead
  changes or loses qualification; cancelled runs revoke pending tool-call approvals
- Internal CRM contact projection and encrypted follow-up drafts created after a
  confirmed booking, with reviewer-only draft approval and a live dashboard queue
- Atomic authenticated website deliveries with frozen replay receipts, concurrent
  deduplication, and monotonic per-enquiry updates
- Dashboard viewing launcher with agent/version selection and native worker
  orchestration through planning, exact approval, booking, CRM, and draft creation
- Approval queue discovery that keeps pending reviews from hiding ready workflows,
  and graph resumption that consumes already-completed booking receipts
- Property-bound booking contracts with listing ID/version in exact approvals and
  validated execution/reconciliation receipts; unavailable listings stop before writes
- Completed bookings retained when leads change, with internal CRM human-review
  routing and blocked follow-up creation
- Encrypted draft editing, optimistic revisions, approval invalidation on edits,
  and approval of the exact reviewed revision in the dashboard
- Organization-scoped per-run booking, CRM, follow-up, and delivery outcomes
- Immutable evaluation dataset versions with validated business-rule expectations
- Saved terminal-run evaluation in a consistent snapshot, frozen reports,
  concurrent replay protection, comparisons, and configurable pass/fail gates
- Evaluation dashboard with case builder, run bindings, check results, comparison,
  report export, and redacted run timelines with recorded model tokens/timing
- Report gate CLI with consistency checks and passing/failing/invalid exit codes
- Native backup archives with shared snapshot manifests, checksum validation, and
  restore rehearsal verified across 41 public tables with encrypted lead decryption
- GitHub unit/type/lint/build workflow configured; hosted CI execution remains open
- Admin-only key issuance, expiry, revocation, identity, and append-only access audit
- Digest-only token storage, one-time token display, and concurrent last-active-admin
  revocation protection with authorization rechecked after organization locking
- Dashboard role identity and key administration without browser token persistence
- Synchronous Python client with HTTPS enforcement outside loopback, redirect
  rejection, sanitized errors, and explicit write replay responsibility
- Separate deterministic support-triage agent/client example with one-run replay
  and zero booking, email, or model calls
- Value-free request-validation errors and API no-store/security response headers
- Real loopback HTTP redirect checks and TLS trust rejection/verified exchange
- Read-only MCP stdio bridge with API-key authentication, initialization, strict
  schemas, tool discovery, safe run summaries, and redacted ledger timelines
- Real MCP subprocess-to-HTTP-to-PostgreSQL acceptance, cross-tenant isolation,
  missing-run denial, and revoked-key denial; remote MCP/OAuth remains open
- General deployment-installed adapter interface with exact contract matching,
  frozen context copies, validated outputs, sanitized uncertain outcomes, and
  worker discovery while retaining approval, budget, lease, and fencing controls
- Durable local SQLite support-ticket adapter with lost-reply recovery after
  adapter recreation, concurrent single execution, and tampered-evidence rejection
- PostgreSQL-backed per-key request limits shared across API instances, committed
  block counts, retry guidance, and verified window reset/independent keys
- Tenant-isolated operational overview and dashboard Operations pulse for pending
  reviews, uncertain outcomes, expired leases, completed calls, and access counters
- Transaction-scoped migration coordination with fresh-database acceptance proving
  two competing starters apply all 18 versions once and replay idempotently
- 78 focused reliability tests, PostgreSQL/API acceptance coverage, and separate
  real-database website/queue checks
- Zero known production npm dependency vulnerabilities at the last audit

## Historical verification: integrated native scheduling (18 September)

All 14 stages of `scripts/release_check.py --profile full` passed with exit code 0.
The atomic report is `.local/release-checks/latest.json`, run
`cb470ec58be4427fb3059c658df6ae31`, completed at 09:22:47 UTC on 18 September.
This includes unit tests, frontend types/lint/build, migration concurrency, adapter
limits, native calendar, website enquiries, access/client, evaluations, stdio MCP,
API recovery, compiled pilot startup and backup/restore. Migration checks cover all
19 versions; restore checks cover all 44 public tables and encrypted lead decryption.
A subsequent serial full unit rerun passed all 139 tests after the final unavailable
slot guard change. The scripted security lab passed all 58 checks across seven
groups, including the new native workflow boundaries.
The subsequent serial failure lab passed all 35 checks; its payload-free report is
`.local/failure-lab/latest.json`. The security report is
`.local/security-lab/latest.json`. Both retain `production_ready: false`.

Native acceptance now exercises the automatic graph as well as the manual calendar
desk. It verifies exact approvals and denial/rejection/expiry, concurrent buyers,
frozen lead/property versions, qualification/consent changes before direct worker
execution, withdrawn/stale slots, cancellation-linked CRM/draft changes, and
committed-result recovery after app recreation without duplicate bookings/drafts.

An initial native acceptance attempt was interrupted after a prolonged run. A
diagnostic run printed passing cases but exited nonzero and was not counted as
clean release evidence. The subsequent normal full-profile native stage passed
with exit code 0. Assertions, verification timeouts and TLS checks were not weakened.
These checks establish functional local regression evidence, not measured capacity,
browser interaction QA, external provider validation or full-product completion.

The compiled local preview was restarted with automatic worker dispatch paused.
Sentinel API health on port 8020, the fictional reference service health on 8022
and the dashboard on 3020 all returned HTTP 200. An earlier reachability check
ran before startup completed and received connection refusal; the subsequent
check passed after the launcher reported ready. This is live HTTP evidence,
not browser interaction QA. Open `http://127.0.0.1:3020` on this laptop.

## Historical verification: earlier local pilot release checks

- All 13 stages in `scripts/release_check.py --profile full` passed on the final run
- All 78 unit tests passed, including real worker redirect checks, frontend-secret
  isolation, and release-check fail-stop/interruption behavior
- Native adapter/rate-limit acceptance passed, including recreation, invalid
  evidence, concurrent claims, two API instances, and isolated counters
- Fresh-database concurrency applied all 18 migrations once and replayed safely
- Full end-to-end API/PostgreSQL suite passed on the final serial rerun
- Frontend TypeScript, lint, and production build passed
- Compiled pilot startup, authenticated identity, and repeated fictional demo
  configuration passed through real local HTTP endpoints
- The compiled launcher stayed running with its worker active. Deliberately stopping
  the verified owned API process triggered supervisor cleanup: all pilot listener
  ports closed, while the pre-existing booking service on port 8002 stayed running.
  The terminal tool's injected Ctrl+C did not deliver a usable interrupt; interactive
  keyboard shutdown was not independently verified in this check.
- Native backup/restore passed across 41 public tables with matching snapshot
  counts and encrypted lead decryption

Earlier end-to-end runs overlapping other checks/builds failed with a client
timeout and an unconfirmed external response. The final run passed after the
frontend build finished. The cause was not isolated; this is functional local
evidence, not proof of latency or capacity under load. Load testing remains a
release requirement. No assertions or runtime timeouts were weakened to pass.

This batch also had an initial lesson-service startup timeout and a failed unit
stage in an earlier full-check attempt. The direct 78-test suite and final full
profile subsequently passed. A transient Windows report-replacement permission
error was addressed with bounded retries while preserving atomic replacement.
These failures are retained here rather than being presented as an uninterrupted
pass. Passing 13/13 checks means 100% of this local checklist passed; it is not an
overall product completion percentage, a security score, or outside pilot evidence.

For the runnable local milestone, use [local pilot](local-pilot.md). Real provider
features and the other broader milestones below remain open.

## Current boundary

A [native viewing calendar](native-calendar.md) now provides timezone-aware slot
offers, availability snapshots, withdrawal, approved reservation/cancellation,
property-version rechecks, serialized overlap prevention, and immutable decision
receipts. Native acceptance passed competing bookings, replay after client
recreation, cancellation and fresh rebooking, committed-result/lost-reply recovery,
withdrawn/changed listings, and tenant isolation. The native path now supports
automatic lead-bound scheduling and internal CRM/draft outcomes through a dedicated,
explicitly enabled agent. Existing reference booking agents remain a separate path.
Staffing/travel capacity and external calendar connections remain open. The manual
calendar UI also covers proposals, review, execution, cancellation, receipt recovery,
and closure.
The native/full release checker includes calendar acceptance (14 full stages), and
the current integrated update passed all 14. Earlier counts below are historical.

Calendar-stage verification: 109 full-suite unit tests passed, followed by the
focused calendar checks after stricter version validation. Native calendar
acceptance and all ten existing API acceptance summaries passed. Fresh competing
startup processes applied all 19 migrations once and replayed idempotently.
Backup restoration matched row counts across all 44 public tables and decrypted
lead data using the separately held key. The rehearsal database was removed.
Those migration and backup checks preceded the calendar desk/dashboard update.

Calendar desk verification (18 September): 116 unit tests passed. Expanded native
calendar acceptance passed concurrent idempotent developer proposals, changed-key
conflicts, role restrictions, exact approvals and revocation, reservation/cancellation,
receipt recovery, manual run closure, and tenant isolation. An initial closure query
used the wrong snapshot location; corrected queries join frozen run-tool permissions.
A later parallel acceptance attempt hit a connection timeout; the final standalone
run passed without changing verification timeouts. TypeScript, targeted lint, and
the production frontend build passed. The restarted compiled preview passed live
reads for all four roles and its browser-origin CORS preflight. No browser was
connected for automation; visual/interaction QA remains open. The full 14-stage
release profile has not been rerun for this update.

Operations pulse now displays the installed reference booking guard's coarse
state and cooldown: dispatch permitted, dispatch paused, or checking recovery.
Refreshing only reads local state; it never probes or writes to the provider.
The signal omits shared failure counts, endpoints, credentials, and buyer data.
It explicitly describes one API process, while ledger counters retain tenant
isolation. A missing reference adapter or older API reports no guard rather than
invented provider health. For this update, all 104 unit tests, TypeScript checking,
and native adapter/rate-limit/counter acceptance passed, including the new guard
snapshot assertions for three authorized roles and elapsed-cooldown behavior.
Frontend lint and the production build also passed. The full 13-stage release
profile was not rerun; its earlier report remains a historical baseline.

The reference booking adapter now has a [process-local circuit breaker](provider-circuit.md).
Repeated temporary provider failures pause new dispatch before approval consumption.
A single read-only health probe after cooldown can reopen dispatch; receipt recovery
remains available while writes are paused. An execution-time recheck preserves
uncertainty if the circuit opens after a ledger claim. The expanded failure lab
passed 35 checks, including 11 circuit-specific tests. Distributed/provider-generic
circuit coordination and real-provider load trials remain open.

For this circuit update, the native API integration suite passed all ten acceptance
summaries, and the subsequent serial full unit suite passed 100 tests. The frontend
is unchanged. The earlier 13-stage release report remains a historical baseline;
it has not been rerun for this update.

A repeatable [local failure lab](failure-lab.md) initially passed all 24 checks, covering
five real-socket booking-provider fault scenarios and the existing
adapter/worker/network checks. The full unit suite subsequently passed 89 tests.
The provider commits a fictional booking before losing its reply; a recreated
client must recover through reads or retain uncertainty, never another write.
Reports contain test identities and status, excluding tracebacks and payloads.
This expands local regression coverage; broader fault injection and circuit
breakers beyond the reference booking provider remain open.

The preceding backend update passed 84 unit tests and the full native API integration
suite; this failure-lab update adds five tests without changing backend runtime code.
The earlier 13-stage full release check is the baseline described above;
it has not been rerun for this update. An initial overlapping unit run hit a lesson
server startup timeout; the subsequent serial suite passed without weakening tests.

The reference booking adapter now retries temporary receipt-read failures at most
three times. It never retries the booking write. Missing, malformed, redirected,
or contradictory receipts stop recovery; exhausted transient failures remain
uncertain for review. Socket timeouts apply to individual network operations, not
an overall hard deadline. This policy does not provide generic adapter retries or
circuit breakers. Six new tests cover retry bounds, evidence mismatch, private
error redaction, configuration checks, and real HTTP redirect refusal.

The local launcher also supports `--preview` for exploring the dashboard while
automatic worker dispatch is paused. This is a local UI preview, not an outside
pilot or production readiness claim.

Versioned runs execute deployment-installed adapters. The default deployment
installs the guarded `book_viewing` bridge and the native reservation/cancellation
calendar tools. Custom adapters match their exact
installed contract and use the existing approvals, budgets, leases, and fencing.
The second durable support-ticket adapter is a local sandbox, not an external CRM.
Reconciliation semantics and external evidence must be implemented and reviewed
per adapter; the generic runtime cannot prove arbitrary external business facts.
Live hosted-model credentials and real calendar/CRM/email providers remain untested.

## Historical integrated-product milestone list

The ordered [release backlog](release-backlog.md) gives concrete deliverables,
pass conditions and external dependencies for the local release and full product.
Use it to prioritize implementation; the historical test counts above are not a
measured completion percentage.

1. Exercise pgvector in a working deployment and measure lexical-versus-vector
   retrieval with a real embedding credential and independently labeled queries
2. Staffing/travel capacity, external calendar sync, CRM/email adapters, and external
   human handoff; automatic native scheduling, internal CRM/draft linkage, property
   slots, overlap prevention, approved cancellation, and durable recovery are implemented
3. Production provider adapters, credentials, outside installation, and more
   integrations; the general adapter interface/runtime and durable sandbox exist
4. Real website deployment and supported additional enquiry integrations; the
   authenticated website delivery API and deduplication boundary are implemented
5. OpenTelemetry instrumentation/export, complete usage coverage, priced costs,
   and redaction testing; ledger timelines and recorded model token/timing views exist
6. Representative/held-out datasets, reference/trajectory and LLM-judge evaluators,
   human calibration, repeated comparisons with uncertainty, online evaluation,
   and deployment-connected gates; immutable datasets/rules/reports plus deterministic
   output/schema/trajectory checks are implemented
7. Broader failure-injection lab, recovery policies, distributed/general provider circuit breakers, and online
   evaluation; native lost-reply, concurrency, recreation, invalid-evidence, and
   shared-rate-limit scenarios are implemented and verified
8. Extend the threat model, real-model prompt-injection and data-leakage campaigns,
   comprehensive trace/log redaction, and security dashboard; the local scripted
   boundary lab and value-free validation diagnostics are implemented
9. Remote MCP/OAuth, MCP dataset/policy access and external-client compatibility,
   external adapter integration, hosted-network/TLS checks, and outside installation;
   read-only authenticated stdio MCP, the Python client, independent agent example,
   and local real-socket/TLS checks are implemented
10. Production user sessions/SSO, invitations, tenant self-service, pre-authentication
    proxy limits/organization quotas, full navigation, and onboarding; service-key
    lifecycle/admin UI and shared authenticated per-key limits exist
11. Hosted CI execution, native service packaging, hosting, secrets, monitoring,
    scheduled/offsite backups, production restore, and load tests; native database
    backup/rehearsal and CI configuration are implemented
12. Outside pilot feedback, reproducible benchmark, release documentation, and demo

## Next standalone milestone

Supported framework adapters and real-agent trials come next: capture actual
externally executed model/tool/retrieval events through documented integrations
and validate output and trajectory rules on representative runs. Finish configurable
runner/facts integration registration and reduce example bootstrap coupling.
Semantic/calibrated evaluation, browser QA, measured capacity, identity/onboarding,
telemetry/costs and independent installation remain standalone priorities.
EstateFlow business expansion is optional reference integration work.

## Historical EstateFlow rollout milestone

Automatic-agent native scheduling integration is now implemented. The next local
release work is integrated browser interaction QA, load testing, native service
packaging and an independent installation/pilot. All 14 full release checks passed
for the integrated scheduling update. External
CRM/email services, calendar synchronization, production user identity, remote
MCP/OAuth and remaining platform capabilities follow the ordered backlog. Read-only
authenticated stdio MCP is available. Per-run action
outcomes, saved-run rules evaluation, and native backup checks now exist. The current
CRM is an internal PostgreSQL projection; approved drafts are not sent. Live
pgvector validation and a real-model retrieval comparison remain open: the native
database runs exact array-cosine search, but its pgvector extension and Docker
engine are unavailable. No paid embedding call has been made; the 12-query
fictional benchmark is a regression fixture, not outside-user validation.

Docker is excluded from the selected development and deployment plan. Local work
uses native PostgreSQL, a Python virtual environment, and project-local Node.
