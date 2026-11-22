# Checking external agent trajectories

Sentinel can apply deterministic policy checks to the finalized trace submitted
for an external agent run. This answers questions such as whether a required
operation was reported, whether important operations occurred in order, whether a
forbidden operation appeared, and whether reported duration, span failures or
model-token usage exceeded a configured limit.

These checks use caller-reported evidence. They do not observe the external agent
independently, prove that every operation was reported, authorize an action, or
judge whether the final answer is true or useful.

## Available requirements

- `required_trace_spans`: every listed operation name must appear.
- `ordered_trace_spans`: listed operations must appear in this order; other spans
  may occur between them.
- `forbidden_trace_spans`: none of the listed operation names may appear.
- `external_reported_status`: match the submitted final status.
- `max_external_duration_ms`: bound the submitted end-to-end duration.
- `max_external_spans`: bound the number of submitted spans.
- `max_failed_trace_spans`: bound spans reported as `failed` or `needs_review`.
- `max_reported_external_tokens`: bound the sum of usage supplied for model spans.
  This check fails when any reported model span omits token usage.
- `reported_model_usage_complete`: require or explicitly test whether every
  reported model span includes usage. This covers only reported spans.

Operation names use lowercase technical identifiers such as `agent.run`,
`retrieval.context`, `model.generate` and `tool.respond`. Required and ordered
operations cannot also be forbidden. Definitions are immutable: change a rule by
creating a new dataset version.

```json
{
  "slug": "support-safe-path",
  "version": 1,
  "cases": [{
    "case_key": "support-request",
    "expected": {
      "required_trace_spans": ["agent.run", "model.generate", "tool.respond"],
      "ordered_trace_spans": ["agent.run", "model.generate", "tool.respond"],
      "forbidden_trace_spans": ["tool.delete"],
      "external_reported_status": "succeeded",
      "max_external_duration_ms": 5000,
      "max_reported_external_tokens": 2000,
      "reported_model_usage_complete": true,
      "max_external_spans": 20,
      "max_failed_trace_spans": 0
    }
  }]
}
```

Submit the dataset to `POST /v1/evaluations/datasets`, bind the case to a terminal
run, and create the experiment through `/v1/evaluations/experiments` or
`SentinelClient.evaluate`. Missing external trace evidence fails every configured
trajectory requirement instead of treating missing values as zero.

## Ordering and privacy

Sentinel reconstructs the reported order from each span's start offset, nesting
depth, duration and stable submission position. A parent precedes a child that
starts at the same offset. The ordering rule checks a subsequence, so unrelated
spans between required operations do not cause a failure.

Trajectory datasets use `agent_rules_v4` reports. Output-only datasets use v3 and
ledger-only datasets use v2. Mixed output-and-trajectory datasets also use v4.
Older saved reports and dataset hashes remain unchanged.

Reports contain boolean verdicts, hashes of private rule definitions, aggregate
reported metrics and caller-reported provenance. They omit configured operation
names. Authenticated dataset reads still expose definitions to authorized users.
The release-gate CLI verifies v4 report consistency but does not authenticate a
downloaded artifact or independently re-run the external agent.

## Verification

`tests/test_trajectory_evaluation.py` covers ordering, required and forbidden
operations, budgets, incomplete usage, missing evidence, validation, privacy and
v4 gate behavior. `tests/acceptance_evaluations.py` verifies the same behavior
through the API and real PostgreSQL, including immutable versions, frozen replay,
tenant isolation and passing/failing CLI exits. The fixtures are synthetic and do
not replace trials with real agents or calibrated semantic evaluation.
