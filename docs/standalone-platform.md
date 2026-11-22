# Sentinel is the product; agents are integrations

AgentOps Sentinel is a developer platform for testing, inspecting and governing
AI agents across domains. EstateFlow is an optional example; the independent
support-triage agent is another. A user's agent does not need property records,
leads, viewing slots or CRM fields to register, create runs or use general
evaluation rules.

## Working entry points

The main dashboard opens on the agent workspace.
The agent library uses a Netflix-inspired browsing structure: a featured agent,
horizontal fleet and recent-activity rows, and agents with failed/review-required
runs in loaded history. Card selection opens the configuration area. The visual
design uses Sentinel graphics and live records, not movie artwork or fabricated
scores. Arrow controls, keyboard-focusable cards and reduced-motion behavior are
implemented. These accessibility mechanisms still require browser verification.

Administrators/developers can
register an agent, save an immutable version and create a run with JSON input.
The workspace lists saved runs and registered tool contracts. Reviewers can read
the workspace; workers use authorized execution/queue endpoints, not these
developer screens. Evaluation screens support terminal status and optional step,
token and model-duration limits. Timelines and saved report comparisons are
available. EstateFlow's controls are under Example integrations and are mounted
only when that example is selected.

API integration order:

1. Register the agent with `POST /v1/agents`.
2. Save its configuration with `POST /v1/agents/{agent_id}/versions`.
3. If it uses controlled tools, register exact contracts and grant the agent tool
   access before creating the run. Dispatch requires a deployment-installed
   adapter matching the contract; registration alone installs no executable code.
4. Record input with `POST /v1/runs`, using a stable idempotency key. Existing
   run permissions and configuration are frozen; new grants do not rewrite them.
5. Your integration executes its agent and uses the worker APIs for controlled
   tool actions and finalization. Follow approval and uncertainty states rather
   than automatically retrying writes. Run creation does not launch an arbitrary
   framework, and the built-in workflow start/resume routes still run the
   EstateFlow graph.
6. Inspect saved tool calls/events/timelines. Bind terminal runs to an immutable
   evaluation dataset and save its experiment report.

The dashboard's `external_agent` model alias is metadata for externally executed
agents. It does not register a model provider. Do not send that alias to the
built-in model gateway without installing compatible routing. See
[access and client](access-and-client.md) and `examples/support_triage_agent.py`.
The Python client now defaults to `external_agent` metadata. Its classifier runs
externally and never invokes a built-in provider. Previously registered versions
are not rewritten: when replaying an old version definition, explicitly pass its
original alias (for example `deterministic_estateflow`) or deliberately create a
new version and use a new run key. Reusing a version/run key with different
configuration correctly returns conflict rather than migrating it silently.

## What general evaluation currently proves

Rules can inspect saved terminal run status, steps used, recorded model token/
duration totals and general tool-call metrics: `completed_tool_calls`,
`failed_tool_calls`, `uncertain_tool_calls`, `max_tool_calls`, and
`required_approvals_consumed`. These are ledger assertions, not proof that an arbitrary answer
is correct. A run finalized by an integration can say succeeded without an
independent judge validating its task result. External model calls are not
automatically captured. Bookings/property/follow-up checks are legacy optional
EstateFlow rules, not universal definitions of agent success.

Generic cases now query only Sentinel ledgers. An isolated EstateFlow collector
runs only when a non-null business expectation explicitly requests it, including
False/zero expectations. New reports use `agent_rules_v2`; old frozen reports
remain unchanged, the gate CLI accepts both supported versions, and comparisons
require matching evaluator and dataset versions.

`completed_tool_calls` counts calls recorded as completed, including tools whose
business result is unavailable; it is not task completion. Uncertain calls are
those recorded as unknown or needs_review. The maximum covers calls of all
statuses. Required approvals checks completed calls against consumed approvals
with the exact stored action hash and tenant. With no completed calls it is true;
combine it with an explicit completed-call expectation when activity is required.
Model budgets cover recorded gateway calls, not automatically captured external
model usage. Zero recorded tokens does not prove an external agent used none.

The built-in start/resume endpoints reject explicit external workflows and
unmarked `external_agent` configurations. They still execute the EstateFlow
example for explicit estateflow runs; unmarked older aliases retain legacy
behavior. Full configurable runner/provider plugin registration is unfinished.
Bootstrap migrations still include the example tables. Existing table names,
migrations and API routes remain compatible so example records and frozen runs
are preserved.

## Remaining standalone work

- Finish configurable domain-facts/runner integration registration and remove
  example requirements from generic runtime/bootstrap initialization. Generic
  facts collection and external-run routing denial are implemented; this is not
  a complete installable plugin system.
- Provide documented adapters for supported external agent frameworks, ingestion
  of external model/tool/retrieval traces and versioned result/output contracts.
  Finalized JSON ingestion, a synchronous Python recorder and dashboard inspection
  are implemented; see [external evidence](external-agent-traces.md). Reports are
  caller-provided, not governed execution proof. LangChain Core/LangGraph callback
  capture is implemented; see [framework tracing](langchain-langgraph-tracing.md).
  Bounded local OTLP/JSON conversion is also implemented; see
  [OpenTelemetry tracing](opentelemetry-tracing.md). An authenticated OTLP/HTTP JSON
  receiver uses immutable pending receipt and explicit output finalization. Protobuf/
  gzip support, additional direct exporters, live AI-agent trials and semantic
  correctness checks remain open.
- Add domain-independent correctness/reference/trajectory evaluators, calibrated
  model judges, representative data, online sampling and release gates.
  Exact JSON-reference and bounded schema checks now use privacy-safe v3 reports;
  deterministic reported-trajectory checks use privacy-safe v4 reports. See
  [output evaluations](output-evaluations.md) and
  [trajectory evaluations](trajectory-evaluations.md). Semantic judges, calibration,
  representative live data and online sampling remain open.
- Finish general tool/grant/policy configuration and exact-action review UI,
  supported edit-and-approve flows, model configuration and onboarding.
- Generalize fault simulation and security campaigns to arbitrary supported
  integrations, with measured limits and false-positive reporting.
- Finish user sessions/tenant onboarding, telemetry/costs/alerts, browser QA,
  measured load limits, service packaging, independent installation and deployment.

Real-estate Instagram, external CRM/email and staff/travel scheduling are optional
EstateFlow integration tasks. They are no longer requirements for releasing
Sentinel itself. Real external integration validation remains necessary to state
which providers/frameworks Sentinel supports. A local full-check pass is evidence
for tested paths, not an overall completion percentage or production claim.
