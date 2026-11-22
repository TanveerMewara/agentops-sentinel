# AgentOps Sentinel investor product tour

Open the presentation at `http://127.0.0.1:3000/tour` after starting the complete
application. Present it full-screen and use the arrow controls in the lower-right.
The embedded product windows are live: click the external-link icon in any window
to open that part of the product in a separate tab.

## The one-sentence pitch

AgentOps Sentinel is the control plane that helps teams observe, evaluate, secure,
and govern AI agents before their decisions create unreliable or irreversible
outcomes.

## Suggested 12-minute presentation

### 1. Opening — the control plane for AI agents

“AI agents are becoming software operators. They choose models, call tools, modify
records, spend money, and communicate with users. AgentOps Sentinel gives the team
one place to understand and control that execution.”

### 2. The problem — action is moving faster than oversight

Explain that a good final answer does not prove that the path was safe or reliable.
The operational question is what the agent called, what it changed, how much it
cost, whether policy allowed it, and whether the external action really succeeded.

### 3. The product — five connected capabilities

- **Observe:** runs, traces, model calls, tools, tokens, latency, and cost.
- **Evaluate:** versioned datasets, deterministic and semantic checks, comparisons,
  and immutable release gates.
- **Govern:** exact-action approval, roles, tool grants, budgets, and audit records.
- **Secure:** organization isolation, encrypted data, redaction, security checks,
  and incident workflows.
- **Recover:** durable workers, retries, reconciliation, circuit breakers, and
  controlled failure testing.

The product is independent of EstateFlow AI. EstateFlow is only one optional
reference integration. Plain Python, LangGraph, OpenAI Agents SDK, OTLP, MCP, and
custom adapters can connect through the general integration boundary.

### 4. Operational overview — see the fleet in one view

Point to the run volume, success rate, failures, latency, token usage, estimated
cost, approvals, and security incidents. Then show the recent runs and control
queue. Explain that the redesigned tour uses clearly marked demo metrics; the
existing connection console exposes the real local backend features.

### 5. Run evidence — explain one execution end to end

Open the live product window and select graph nodes. Show the request, router,
model, tool, policy, approval, output, and evaluation stages. Explain that each
node can carry status, timing, model, token, cost, tool, retry, and evaluation
evidence. The ordered fallback list makes the flow accessible without the graph.

### 6. Governance — approval is different from execution

Use a financial or data-export action as the example. A reviewer approves exact
arguments. Sentinel rechecks permission, expiry, revision, and policy before a
worker claims the action. The operation ledger records the attempt and outcome.
If the external reply is lost, Sentinel preserves `UNKNOWN` until evidence proves
success; it does not blindly repeat a potentially irreversible write.

### 7. Quality and resilience — test releases and recovery

Evaluation considers task success, tool selection, groundedness, compliance,
latency, and cost together. The Failure Lab injects controlled timeouts, malformed
outputs, rate limits, refusals, network loss, and policy violations so recovery
behavior can be verified before production.

### 8. Architecture — an evidence loop around every action

Agents integrate through REST, OpenTelemetry, MCP, framework callbacks, or custom
adapters. FastAPI validates identity and contracts. PostgreSQL preserves versions,
approvals, leases, attempts, outcomes, telemetry summaries, and evaluation reports.
Workers execute bounded actions. The dashboard turns this evidence into operational
decisions. The loop is capture, evaluate, approve, execute, reconcile, improve.

### 9. Verified local evidence — show what has actually passed

As of 21 September 2026, the repository records a passing 23-stage Docker-free
local profile, 217 unit tests, 62 security checks, 35 failure checks, 24 migrations,
a verified 64-table restore, and 80 of 80 writes under the measured local gate.
The recorded local capacity was 25.60 requests per second with 610 ms p95 at
concurrency eight. State clearly that this is local release evidence, not a public
production or customer-scale benchmark.

### 10. Technology — designed for integration and proof

- React 19, TypeScript, Vinext, and Lucide for the operator experience.
- Python, FastAPI, and Pydantic for typed APIs and worker boundaries.
- LangGraph and OpenAI Agents SDK integration examples.
- PostgreSQL 17 for durable multi-tenant ledgers and encrypted records.
- OpenTelemetry, REST, MCP, and a Python client for interoperability.
- pytest, ESLint, TypeScript, CI configuration, backup/restore, failure, security,
  migration, and release checks for verification.

### 11. Readiness — be explicit about the commercial boundary

The durable local release and its automated verification exist today. A public
production claim still requires an independent pilot, hosted identity and
operations, real provider integrations, representative datasets and workloads,
connected-browser QA, offsite recovery, and external performance validation.
This honesty is part of the product: uncertainty is shown instead of hidden.

### 12. Close — propose a design-partner pilot

Ask the prospective partner to choose one real agent and one high-impact workflow.
Define its action contract, approval policy, quality gates, and success measures.
Connect it to Sentinel and measure reliability, intervention, latency, and cost
together. Expand only when the evidence supports it.

## Questions an investor or design partner may ask

**How is this different from a trace viewer?**  
Tracing explains what ran. Sentinel connects traces to authorization, durable
operation identity, external outcome reconciliation, evaluations, release gates,
failure testing, and incident response.

**Does it work with any agent?**  
It is domain-independent and has general APIs and adapters. Every integration must
explicitly supply the evidence and action contract that Sentinel can verify. It
cannot automatically see or prove facts that an integration does not expose.

**Does it prevent hallucinations?**  
No system can promise universal correctness. Sentinel runs configured evaluations,
policy controls, and evidence checks, and shows the limits of each result.

**Why is PostgreSQL central?**  
Agent operations need durable identity and transactional state. PostgreSQL stores
what was requested, approved, attempted, observed, and evaluated across crashes and
restarts. The queue delivers work; the ledger remains the record of truth.

**What is the first commercial wedge?**  
Teams deploying agents that take high-impact tool actions and need release evidence,
human control, and reliable recovery. A design-partner pilot should focus on one
agent whose failures or manual oversight already create measurable cost.

**What would funding accelerate?**  
Independent pilots, hosted operations, production identity, more framework/provider
adapters, real-world evaluation datasets, monitoring integrations, and externally
validated security, recovery, and capacity evidence.

## Evidence boundary

The tour separates implemented local capabilities, demonstration data, and future
commercial milestones. It should not be presented as proof of public production
readiness, universal agent safety, or adoption that has not yet occurred.
