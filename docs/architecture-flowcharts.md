# Architecture explained through flowcharts

These diagrams show the intended full product, combining the original Sentinel
proposal and the additional reliability work. They are not a claim that all parts
exist today. PostgreSQL directly on Windows is now the selected local setup;
installation and persistence verification have passed. Docker is excluded from
the selected workflow. Native processes and a managed database are the deployment
alternatives; the existing optional container example is not required.

## 1. The complete product

The adapter runtime now supports deployment-installed custom contracts in addition
to default booking. A durable local support-ticket sandbox verifies the second
adapter path. PostgreSQL shares per-key request limits across API instances, and
the dashboard displays tenant-scoped operational counters. Real external
calendar/CRM/email providers and hosted validation remain target architecture.

The native scheduling path now connects a qualified lead's frozen version to an
offered property slot, exact-action approval, an overlap-safe native reservation
and internal CRM/follow-up records. Cancellation invalidates linked unsent drafts.
The original fictional booking configuration remains separately supported; neither
path proves a real external calendar/CRM/email integration. See the
[automatic native workflow](native-calendar.md#automatic-lead-bound-native-workflow).

The currently implemented MCP path is a desktop subprocess calling the Sentinel
API with an environment-provided service key. It exposes only identity, safe run
summaries, and redacted timelines. Remote MCP/OAuth and dataset/policy tools remain
target architecture. See [MCP integration](mcp-integration.md) for setup and limits.

```mermaid
flowchart TD
    Customer["Customer: website or Instagram enquiry"] --> Estate["EstateFlow agent: understand, retrieve, propose"]
    Other["Another developer's agent"] --> API["Sentinel API: identity, permissions, validated requests"]
    Estate --> API
    Estate <--> Models["Model gateway: providers, prompt versions, routing"]
    Estate <--> Properties["Property retrieval: PostgreSQL and pgvector"]
    Developer["Developer or reviewer"] <--> UI["React dashboard: runs, approvals, evaluations"]
    UI <--> API
    MCPClient["Authorized MCP client"] <--> MCP["Scoped MCP interface"]
    MCP <--> API
    API --> Policy["Action policy: validate details and required approval"]
    Policy --> Approval["Approval: exact details, expiry, revocation"]
    Approval --> Ledger["Durable operation ledger: authorized work and attempts"]
    Policy -->|"Approval not required by policy"| Ledger
    Ledger --> Worker["Background worker: execute or reconcile"]
    Worker <--> Adapter["Tool adapter: service-specific requests and evidence"]
    Adapter <--> External["External services: booking, CRM, messaging"]
    Worker --> Ledger
    API <--> DB[("Sentinel PostgreSQL: users, operations, approvals, versions")]
    Ledger <--> DB
    API -.-> Capture["Telemetry collection and redaction"]
    Estate -.-> Capture
    Worker -.-> Capture
    Capture --> Trace[("Protected trace storage: steps, tools, latency, tokens, estimated cost")]
    Trace --> Evaluate["Evaluation: offline tests and sampled online scoring"]
    Cases["Versioned test datasets and human labels"] --> Evaluate
    Lab["Controlled failure and security tests"] -->|"Test environment only"| Worker
    Evaluate --> Results[("Evaluation results and version comparisons")]
    Results --> API
    Trace --> API
    Results --> Gate["CI quality checks and release decision"]
    Trace --> Alerts["Monitoring and alerts"]
    Alerts --> UI
```

Solid arrows represent requests or data flow; dotted arrows collect telemetry.
Read the main action path from top to bottom. The bottom branches inspect, test,
and improve the system; they are not all mandatory steps in every booking.
The storage boxes show responsibilities, not a requirement for separate servers
or databases. EstateFlow business data and Sentinel control records must have
clear ownership even if local development initially shares a PostgreSQL instance.

EstateFlow solves the property business task. Sentinel controls and inspects the
agent's actions. Other agents can use Sentinel without using EstateFlow.

## 2. One appointment request

```mermaid
flowchart TD
    Request["Customer asks for a property viewing"] --> Agent["EstateFlow finds a property and proposes exact details"]
    Agent --> Validate{"Valid action and permitted user?"}
    Validate -->|"No"| Denied["Reject and record the reason"]
    Validate -->|"Yes"| Need{"Does policy require approval?"}
    Need -->|"Yes"| Review["Show exact action to an authorized reviewer"]
    Review --> Decision{"Reviewer decision"}
    Decision -->|"Reject"| Denied
    Decision -->|"Edit"| Agent
    Decision -->|"Approve"| FinalCheck{"Permission, expiry, and exact details still valid?"}
    Need -->|"No"| FinalCheck
    FinalCheck -->|"No"| Denied
    FinalCheck -->|"Yes"| Commit["Atomically record authorized operation and consume approval if required"]
    Commit --> Queue["Queue work for a background worker"]
    Queue --> Execute["Worker records attempt and invokes tool adapter"]
    Execute --> Service["Booking service performs the action"]
    Service --> Evidence{"Trustworthy matching result received?"}
    Evidence -->|"Yes"| Success["Record success and booking ID"]
    Evidence -->|"No or timeout"| Unknown["Record UNKNOWN and reconcile"]
    Success --> Followup["Continue CRM and notification steps under their own policies"]
    Followup --> Display["Return progress or result to customer; show trace in dashboard"]
```

Approval and execution are different. Saving authorized work does not mean the
external appointment exists. Likewise, booking success does not mean a later CRM
update succeeded. Each external action has its own identity and recorded outcome.
The queue is a delivery mechanism; the ledger is the durable record of work. A later
implementation must bridge database commit and queue delivery reliably.

## External agent telemetry and finalization

```mermaid
flowchart TD
    Agent["External AI agent with OpenTelemetry instrumentation"] --> Exporter["OTLP/HTTP JSON or Protobuf exporter\nOptional gzip"]
    Exporter -->|"/v1/traces + API key + run ID"| Receiver["Sentinel authenticates, bounds and converts the trace"]
    Exporter -->|"/v1/metrics"| Metrics["Aggregate tokens and model/tool/retrieval latency\nApply explicit versioned rate card"]
    Exporter -->|"/v1/logs"| Logs["Count severity and correlation\nDiscard bodies and attributes"]
    Receiver --> Pending["Immutable pending structural evidence\nNo output and not evaluable"]
    Agent --> Result["Integration prepares sanitized final JSON output and status"]
    Result --> Finalize["Finalize the pending trace with a stable idempotency key"]
    Pending --> Finalize
    Finalize --> Frozen["Immutable finalized external evidence"]
    Frozen --> Evaluate["Output, schema and trajectory evaluation"]
    Frozen --> Inspect["Authorized trace inspection; output hidden by default"]
    Metrics --> Summary["Run telemetry summary"]
    Logs --> Summary
    Pending --> Summary
    Policy["Required signals, usage/cost rules and retention"] --> Summary
    Policy --> Purge["Expiry purge or admin run deletion"]
```

Receipt and finalization are separate so an exporter cannot accidentally claim that
an empty object is the agent's real output. Replayed identical telemetry/finalization
is safe; different evidence for the same run conflicts. Telemetry is caller-reported
and does not authorize external actions or change governed tool/model ledgers.

## 3. Recovery when a reply goes missing

```mermaid
flowchart TD
    Sent["One booking request sent"] --> Timeout["Reply missing or unusable"]
    Timeout --> Unknown["UNKNOWN: Sentinel cannot establish the outcome"]
    Unknown --> Capability{"What recovery does this service support?"}
    Capability -->|"Reliable operation lookup"| Lookup["Read result for the same operation ID"]
    Lookup --> Match{"Matching completed booking found?"}
    Match -->|"Yes"| Success["Record SUCCEEDED with verified booking ID"]
    Match -->|"No, mismatch, or unavailable"| Review["Keep uncertainty visible; request human reconciliation"]
    Capability -->|"Guaranteed idempotent replay"| Replay["Replay same operation ID and exact details within service guarantees"]
    Replay --> Result{"Matching success confirmed?"}
    Result -->|"Yes"| Success
    Result -->|"No"| Review
    Capability -->|"Neither capability"| Review
```

The lookup branch is demonstrated in Lesson 5. The replay-capability branch is
planned, not yet part of that execution loop. Services supporting both can use
lookup first. 'Not found' does not automatically authorize another write. Recovery
rules must account for pending requests, stale reads, and idempotency-key retention.

## 4. Our local setup choice

```mermaid
flowchart LR
    Browser["Browser: React operations dashboard"] --> Python["Python API and workers in .venv"]
    Python --> Driver["Psycopg: PostgreSQL connection driver"]
    Driver --> Postgres["PostgreSQL running directly on Windows"]
    Postgres --> Disk[("Database files on local disk")]
```

This is the selected and verified development setup. Native PostgreSQL 17.11 runs
from the ignored project-local directory and has passed persistence, restart,
transaction, concurrency, API, and workflow-checkpoint checks.

## What exists today

- Implemented: durable multi-tenant operation and run ledgers, exact approvals,
  leased workers, evidence-only crash recovery, agent/tool registry, model gateway,
  encrypted provider credentials, and PostgreSQL-checkpointed LangGraph workflow.
- Implemented: professional React dashboard and property-search interface plus
  versioned EstateFlow ingestion, evidence-backed full-text/trigram retrieval,
  versioned embeddings, exact array-cosine search, and frozen per-run
  recommendations inside the durable workflow.
- Implemented: encrypted lead intake, rule-based qualification, human-review
  routing, and a lead-bound booking gate that rechecks the lead before execution.
- Implemented: internal CRM contact projection and encrypted follow-up drafts with
  reviewer approval, created durably after confirmed lead bookings.
- Implemented: property-bound booking ID/version evidence, availability checks
  before execution, post-booking lead-change review, encrypted draft editing with
  revision-specific approval, and independently reported per-run action outcomes.
- Implemented: versioned business-rule evaluation datasets, frozen saved-run
  reports, comparisons, a gate command, and dashboard evaluation/run timelines.
- Implemented: native database backups and temporary restore rehearsal with
  snapshot table counts and preserved encrypted lead readability.
- Implemented: service-key lifecycle/admin UI, access audit and concurrent admin
  protection, Python HTTP client, and a separate read-only support-triage example.
- Prepared: optional pgvector migration and deployment configuration. Its exact
  pgvector query path still needs a working extension and live validation.
- Planned: later EstateFlow actions and external enquiry/handoff integrations, tracing,
  evaluation/security labs, MCP integration, production identity, and deployment.

The website delivery API now deduplicates retries and rejects stale updates. The
dashboard queues viewing runs, and the native worker advances them through exact
approval and booking. External adapter interfaces remain a next milestone.
CRM currently means an internal database projection, and draft
approval does not send email. Live pgvector validation and a measured real-model
retrieval comparison remain open.

