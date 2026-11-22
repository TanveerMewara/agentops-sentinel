# Evaluations and run timelines

Sentinel can evaluate saved terminal runs against immutable, organization-scoped
dataset versions. Evaluation never starts an agent, repeats a tool action, or calls
a model. The first evaluator is deterministic `business_rules_v1`.

The dashboard's **Evaluation and execution evidence** panel creates a regression
case, binds saved runs to dataset cases, shows individual checks, compares reports,
exports JSON, and opens a redacted event timeline. The API supports datasets of up
to 100 cases, including richer combinations than the dashboard's single-case builder.

```json
{
  "slug": "estateflow-booking",
  "version": 1,
  "cases": [{
    "case_key": "qualified-buyer",
    "expected": {
      "run_status": "succeeded",
      "completed_bookings": 1,
      "property_bound": true,
      "approvals_consumed": true,
      "followup_status": "draft",
      "max_steps_used": 12,
      "max_model_tokens": 2000
    }
  }]
}
```

Create this definition with `POST /v1/evaluations/datasets`. Repeating the same
slug/version/definition returns the existing dataset. Changing a definition needs
a new version; conflicting reuse returns 409. Cases cannot be empty, have duplicate
keys, or include unrecognized fields. Dataset creation requires admin/developer.

`POST /v1/evaluations/experiments` requires a dataset ID, an `idempotency_key`,
`bindings` mapping every case key to a saved run ID, and an optional `min_pass_rate`
(default 1.0). Every binding must belong to the caller's organization and reference
a terminal run. Experiments can be created by admin/developer/reviewer.

Evaluation reads all business facts in one repeatable-read PostgreSQL snapshot.
It stores those facts and each expected/actual check in a frozen report. Concurrent
retries share a key lock and return one report. Reusing a key with a changed request
returns 409. Later draft edits or status changes do not rewrite existing reports.

Supported checks cover run status, completed booking-call count, property argument
binding, consumption of required approvals, human-review requirement, follow-up
status, step budget, recorded model tokens, and recorded model duration. Booking
counts measure completed ledger calls; they are not independent proof of supplier
side effects. Approval checks do not claim approvals are mandatory for every
possible tool contract. Model budgets measure recorded invocation accounting.

Compare reports with `GET /v1/evaluations/compare?left=...&right=...`. The API requires
the same immutable dataset version and reports the pass-rate delta. Run facts include
agent-version IDs, so callers can bind runs from different versions. A small or
synthetic comparison does not establish statistical significance or overall model
quality. Reference/trajectory evaluators, LLM judges, human calibration, held-out
datasets, repeated-run uncertainty, and sampled online evaluation remain open.

Export a report from the dashboard and check it in an automation:

```powershell
.\.venv\Scripts\python.exe scripts\evaluation_gate.py path\to\report.json
```

The command exits 0 for a passing gate, 1 for a failing gate, and 2 for an invalid
report. It recomputes checks and totals rather than trusting the summary pass flag.
It expects a trusted Sentinel export; reports are not cryptographically signed and
the command cannot prove the authenticity of edited source facts.

`GET /v1/runs/{run_id}/timeline` combines run, model, retrieval, and engagement events
with tokens and timing. Event payloads, prompts, arguments, outputs, and contact
fields are omitted. Technical identifiers remain. This is a ledger-based timeline,
not OpenTelemetry instrumentation. Cost is explicitly null until pricing and usage
coverage are configured. Redaction does not detect secrets hidden in user-chosen
technical names. Access is organization-scoped for the existing platform roles.

`.github/workflows/checks.yml` configures backend unit checks and frontend type/lint/
build checks. It has not yet run in a hosted repository. Native PostgreSQL acceptance
remains a local check, and the evaluation report gate is not yet attached to an actual
production deployment pipeline. No Docker is required.

```powershell
.\.venv\Scripts\python.exe tests\acceptance_evaluations.py
```

Acceptance uses synthetic saved-run facts for isolation, replay, report freezing,
redaction, comparisons, and CLI checks. These fixtures are not a published quality
benchmark or evidence of a real customer booking.
