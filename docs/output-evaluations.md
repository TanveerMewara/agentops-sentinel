# Checking external agent outputs

Sentinel can evaluate the JSON output in a finalized external trace against a
reference object and a bounded JSON schema. These are deterministic requirements
checks. They do not judge the truth of prose, prove safety, or prove that external
actions had Sentinel approval. Evidence remains caller-reported.

## Workflow

1. Register an external agent/version and create its run.
2. Execute your agent and submit finalized evidence using the
   [trace recorder/API](external-agent-traces.md).
3. Close the eligible governed run separately with an admin/worker key through
   `complete_run`. This existing closure does not verify the reported external
   outcome. Offline evaluation requires a terminal run.
4. Create an immutable evaluation dataset with output expectations; bind its
   cases to saved run IDs and evaluate through the UI or existing Python client.

In **Evaluation and execution evidence**, expand **Check submitted output**.
Enter optional expected-output and schema JSON. Blank fields skip their check.
Alternatively use the additional-expectations JSON field or dataset API:

```json
{
  "slug": "support-quality",
  "version": 1,
  "cases": [{
    "case_key": "support-result",
    "expected": {
      "output_equals": {"category": "billing", "priority": "normal"},
      "output_schema": {
        "type": "object",
        "required": ["category", "priority"],
        "additionalProperties": false,
        "properties": {
          "category": {"enum": ["billing", "technical"]},
          "priority": {"enum": ["normal", "urgent"]}
        }
      }
    }
  }]
}
```

POST this definition to `/v1/evaluations/datasets`. Then use
`client.evaluate(dataset_id, stable_experiment_key, {"support-result": run_id})`.
Both configured checks must pass the default all-cases gate. Existing governed
status/tool/model-budget rules can be combined with these checks; external token
reports are not added to governed budgets. Missing external output fails even an
empty schema or reference; it does not silently skip a requirement.

## Meaning and limits

- `output_equals`: identical object keys and recursively matching values. Object
  key order is irrelevant, array order matters, and strings match exactly without
  case/whitespace normalization. Numbers compare by value (`1` equals `1.0`),
  while booleans remain distinct from numbers (`true` does not equal `1`).
- `output_schema`: supported Draft 2020-12 keywords are `type`, `properties`,
  `required`, `additionalProperties`, `items`, `enum`, `const`, `minLength`,
  `maxLength`, `minItems`, `maxItems`, `minimum`, `maximum`, `exclusiveMinimum`,
  `exclusiveMaximum`, `minProperties` and `maxProperties`. Boolean child schemas
  are allowed. An optional `$schema` must name the Draft 2020-12 dialect.
- `$ref`, regex/patterns, formats and schema combinations are rejected; no remote
  schema fetching is performed. Schema trees are bounded to depth 16/256 nodes.
- Each rule definition is at most 16 KiB of finite JSON. Datasets are bounded
  to 256 KiB normalized JSON and 512 KiB transport before parsing, and retain the
  existing maximum 100 unique cases. Submitted outputs remain JSON objects.

A different but equally good free-form answer can fail exact matching. Use these
checks for structured contracts and deterministic tasks. Deterministic reported
trajectory checks are documented in [trajectory evaluations](trajectory-evaluations.md);
semantic judges, representative references and calibrated scoring remain open.

## Reports, privacy and compatibility

Output-only datasets produce `agent_rules_v3` reports. Datasets with trajectory
rules, including mixed output-and-trajectory cases, produce `agent_rules_v4`.
Ledger-only datasets continue using `agent_rules_v2`; existing stored reports
replay unchanged. New absent/null
output fields are omitted from dataset hashes to preserve older definition replay.
Change requirements by creating a new dataset version. Comparisons still require
the same dataset and evaluator version.

Checks export boolean expected/actual results, definition hashes and generic
match/mismatch/missing-output reasons. Facts include trace ID/hash and the
caller-reported provenance. Reports omit raw outputs, reference values, schema
property names and validation errors. Authenticated dataset reads still include
the reference/schema definitions; these are not automatically secret-redacted.

The existing `scripts/evaluation_gate.py` supports legacy, v2, v3 and v4 exports and
checks internal pass/total consistency. It does not sign reports, independently
recompute output checks, or authenticate a downloaded artifact. Secure CI artifact
provenance and deployment wiring remain open.

## Verification

`tests/test_output_evaluation.py` covers matching, mismatches, numeric/boolean
distinctions, nested schema validation, rejected unsafe features, size/depth bounds,
missing evidence, tenant filters, privacy and export checks.
`tests/acceptance_evaluations.py` exercises actual PostgreSQL saved traces/datasets,
passing/failing/missing-output reports, immutable version replay, comparison,
tenant isolation, value-free validation and gate CLI exits. Fixtures are synthetic;
they are not live AI quality measurements or browser interaction verification.
