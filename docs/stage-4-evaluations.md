# Stage 4: calibrated evaluation and release gates

Stage 4 turns Sentinel's existing exact-output and trajectory checks into a broader
release decision system. It adds declared dataset coverage, semantic judging,
human calibration, repeated-run uncertainty, variant comparison, online sampling
and immutable release gates.

## Representative and held-out datasets

Every case may declare:

- `category`: a bounded analysis group such as `billing`, `technical` or `safety`;
- `split`: `development`, `validation` or `test`;
- `weight`: the case's contribution to the experiment pass rate;
- existing exact output, schema, trajectory and budget expectations;
- an optional `semantic_judge` rule.

A dataset can declare `coverage.min_categories` and
`coverage.min_cases_per_category`. Creation fails when its own coverage claim is
not met. Experiment reports freeze the category distribution, total weight and
whether every case is held out (`split=test`). These fields document the sampling
frame; they cannot prove that the author's cases represent real production traffic.

## Semantic judge

The semantic rule contains a bounded criterion, reference JSON, minimum score,
configured model alias and one to five repetitions. Only admin/developer service
keys may start provider-backed semantic experiments. The output being judged must
come from finalized immutable external evidence.

The OpenAI adapter uses the Responses API with a strict JSON Schema response,
`store=False`, no tools and a 200-token output limit. It accepts only a score from
0 to 1, a consistent pass/fail label and fixed diagnostic flags. Malformed or
failed provider responses fail closed. Sentinel stores aggregate score, standard
deviation, token count, duration, hashes and the verdict. It does not store model
rationale, criterion/reference content, provider response text or the candidate
output in the experiment report.

The provider still receives the criterion, reference and candidate output. Creating
a semantic dataset and starting its experiment is therefore an explicit disclosure
decision. Configure a dedicated provider alias and follow the provider's data policy.

The production adapter follows the current OpenAI Responses structured-output
contract. Stage 4 acceptance uses a deterministic scripted judge at the same
interface because no live evaluation credential is available in the local release.

## Human calibration

Reviewers and administrators submit immutable scores through
`POST /v1/evaluations/human-labels`. A reviewer may label a dataset case/run pair
once. Replaying the identical label is safe; changing it conflicts.

`POST /v1/evaluations/calibrations` compares semantic scores with matching human
labels. A calibration requires at least three labels and freezes:

- mean absolute score error;
- pass/fail agreement;
- judge-configuration hashes;
- thresholds and final verdict.

The calibration identity includes the exact human-label snapshot, so adding labels
creates a new calibration rather than rewriting an older result.

## Repeated experiments and comparisons

`POST /v1/evaluations/analysis` accepts two to fifty immutable experiments from
one dataset/evaluator version. It returns mean pass rate, population standard
deviation, a descriptive 95% interval, min/max, held-out status, category results
and variant metadata. An experiment variant can identify prompt, model alias and
retrieval version. The regular comparison endpoint now reports pass-rate,
category and semantic-score deltas plus the two variants.

The interval describes the supplied repetitions; it does not establish population
confidence when runs are not independently sampled.

## Release gates

`POST /v1/evaluations/release-gates` freezes a candidate decision over at least two
experiments. It can require:

- minimum mean pass rate;
- maximum pass-rate standard deviation;
- test-only held-out data;
- a passed human calibration for semantic evaluator v5;
- no regression beyond a configured tolerance against baseline experiments.

Reports are immutable and idempotent. `scripts/release_gate.py` independently
recomputes the final Boolean decision for CI. A semantic release cannot pass without
a matching, passed calibration.

## Online sampling

An administrator configures one organization policy at
`PUT /v1/evaluations/online-policy`: an immutable single-case dataset, case key,
sample rate, daily selected-run limit and enabled state. A worker calls
`POST /v1/runs/{run_id}/evaluation-sample` after the run becomes terminal.

Selection is deterministic for organization, run and dataset. The organization row
serializes daily-limit checks, and each run is considered once. Selected runs create
an ordinary immutable experiment through the internal policy-controlled path.
Replays return the same experiment. This endpoint does not silently intercept every
run; the worker or deployment must call it.

## API and trust boundary

Read endpoints expose human-label metadata without reviewer key IDs, calibration
reports, release-gate reports and the current online policy. All rows are tenant
scoped. Rules, references, outputs and free-form model explanations are absent from
calibration, analysis and release reports.

Model judging and human agreement measure configured quality criteria. They do not
prove factual truth, safety or representativeness. Release gates combine declared
evidence and fail closed when required calibration, held-out data, stability or
baseline behavior is missing.
