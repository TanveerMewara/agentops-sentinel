# AgentOps Sentinel benchmarks

This benchmark produces local, reproducible evidence for failure diagnosis,
latency, monitoring overhead, engineering scale, token and cost analytics, test
coverage, and reliability. It does not represent production-user traffic.

## Run it

From the repository root on Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts\run_benchmarks.py
```

The command runs the discoverable backend unit suite under branch coverage and
then writes:

- `reports/benchmark_results.json`: complete structured evidence, confusion
  matrix, per-category scores, environment, hashes, raw latency samples and
  limitations;
- `reports/benchmark_results.csv`: flat headline metrics;
- `reports/benchmark_summary.md`: human-readable results and evidence boundaries;
- `reports/resume_metrics.md`: only claims supported by that benchmark run;
- `reports/test_metrics.json` and `reports/coverage.json`: test and coverage
  evidence.

Use `--skip-tests` only to reuse an existing passing `test_metrics.json`. The
normal command reruns tests. `--repetitions`, `--load-executions`, and
`--concurrency` are bounded so accidental invocations cannot create unbounded
local load.

## Environment identity

Every report records the UTC completion time, operating system, architecture,
processor information when available, logical CPU count, physical memory when
available, Python version, dataset SHA-256, and a deterministic source-tree
SHA-256. This workspace currently has no Git metadata, so `git_commit` is `null`.
The source-tree hash identifies the measured Python, SQL, benchmark, test, and
dataset files until the project is placed in Git.

PostgreSQL is not required for this controlled benchmark. Existing PostgreSQL
acceptance and capacity checks remain separate release evidence. This separation
keeps the monitoring comparison focused on agent-side instrumentation rather
than database or network variability.

## Failure dataset and detector

`datasets/failure-detection-v1.json` is immutable by convention and identified by
its content hash. It contains successful controls plus these primary failures:

- tool execution failure;
- timeout;
- invalid tool arguments;
- malformed LLM output;
- hallucinated or unsupported response;
- API failure;
- retry exhaustion;
- routing failure;
- retrieval failure;
- validation failure.

Each case supplies bounded structured signals, a primary ground-truth label, and
explicit reliability outcomes. No prompt, response, tool argument, exception
message, or private content is used. `sentinel.failure_diagnostics` applies a
documented deterministic precedence when multiple normalized signals are present.
The corpus intentionally includes a few overlapping-signal cases to test this
precedence.

The current dataset and detector were developed together. A perfect score on this
controlled corpus establishes deterministic conformance, not external validity.
Generalization requires a separately authored, held-out dataset based on real
incident labels.

For every class, the report computes one-vs-rest values:

```text
precision = TP / (TP + FP)
recall    = TP / (TP + FN)
F1        = 2 * precision * recall / (precision + recall)
```

Zero denominators produce zero rather than an invented perfect value. Overall
accuracy is correct predictions divided by all predictions. Macro metrics average
classes equally; weighted metrics weight by class support; micro metrics aggregate
all multiclass decisions. The JSON report stores the complete confusion matrix and
every misclassification identifier.

## Latency methodology

The runner executes three arms:

1. **Baseline** performs the deterministic agent workload without Sentinel
   instrumentation.
2. **Observed** performs identical model and tool work with `TraceRecorder` and
   structured failure diagnosis.
3. **Optimized** retains monitoring while applying an exact-key deterministic
   model-call cache and removing repeated prompt context.

Baseline and observed order alternates on each repetition to reduce systematic
warm-cache bias. Three scenarios per arm warm the interpreter and validators;
warm-up samples are discarded. Every scenario is then measured for the configured
number of repetitions using `time.perf_counter_ns()`.

The report measures total workflow, model-call, tool-call, and failure-detection
latency. P50, P95, and P99 use the nearest-rank definition:

```text
rank = ceil(number_of_samples * percentile)
```

Monitoring overhead is the paired observed total minus its identical baseline
total. Negative samples are retained and counted. Mean overhead percentage is:

```text
(mean_observed - mean_baseline) / mean_baseline * 100
```

The optimized arm is not used to claim monitoring overhead. It demonstrates a
specific reference-workflow optimization and is reported separately.

## Token and cost methodology

The offline benchmark uses a deterministic synthetic provider. Its token unit is
the count of whitespace-delimited pieces in the exact benchmark input or output.
Reports label these as **synthetic token units**, not real model tokens. The
declared synthetic rate card is stored in every result. Estimated cost is:

```text
(input_units * input_rate + output_units * output_rate) / 1,000,000
```

Cost per successful task divides estimated cost by successful final outcomes.
The optimized comparison uses the same scenarios and outcomes, removes one
redundant deterministic model call through exact-key caching, and reduces repeated
context. The report calculates reductions from measured token units and costs.
This is not a provider invoice and does not prove that Sentinel automatically
optimizes arbitrary agents.

Real provider usage remains supported by Sentinel's model-invocation and OTLP
telemetry paths. Resume claims must use the offline synthetic qualifier unless a
separate live-provider benchmark captures provider-reported usage and its rate-card
version.

## Reliability and scale

Reliability values come from explicit outcomes in every controlled scenario:

- success rate = successful final outcomes / executions;
- failure rate = failed final outcomes / executions;
- retry success rate = successful retries / scenarios where retry was attempted;
- recovery rate = recovered outcomes / scenarios where recovery was attempted;
- tool success or failure rate = successful or failed tool calls / all tool calls.

The concurrent load phase uses a bounded thread pool and the observed arm. It
reports simulated concurrent agents, executions, generated traces, spans, monitored
tool calls, throughput, and latency percentiles. These values describe a local
single-process synthetic workload and cannot be presented as hosted capacity.

## Tests and coverage

`scripts/run_test_metrics.py` discovers `tests/test_*.py` using `unittest`, records
passed, failed, error, and skipped counts, and measures branch coverage over
`src/sentinel`. Migration SQL, frontend TypeScript, and standalone PostgreSQL
acceptance scripts are outside this coverage percentage. Important-module coverage
is listed separately so a high aggregate cannot hide a critical untested module.

The full existing native release command remains:

```powershell
.\.venv\Scripts\python.exe scripts\release_check.py --profile full
```

## Limitations

- The failure distribution is synthetic and balanced for evaluation, not sampled
  from production incidents.
- Detector and corpus conformance does not prove performance on unseen agents.
- Synthetic token units are unsuitable for real billing claims.
- Microbenchmarks are sensitive to host load, power settings, and background work.
- Local thread concurrency does not represent distributed or multi-host scale.
- Backend unit coverage does not include frontend code or standalone acceptance
  subprocesses.
- Monitoring improves evidence and diagnosis; it does not by itself improve task
  success. The observed arm therefore preserves baseline outcomes.

Retain the generated JSON alongside any resume or interview claim. A reviewer can
recompute each headline value from its raw samples, confusion matrix, dataset hash,
and declared formulas.
