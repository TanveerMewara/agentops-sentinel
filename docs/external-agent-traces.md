# External agent evidence

Sentinel accepts a finalized trace and JSON output from independently executed
agents. EstateFlow is not required. The Python recorder is synchronous and
framework-independent. A supported LangChain Core/LangGraph callback adapter and
a bounded local OTLP/JSON converter are available. An authenticated OTLP/HTTP JSON
receiver stores pending structural evidence until explicit output finalization.
Protobuf/gzip transport, other direct exporters and real AI-agent trials remain open.
See [LangChain/LangGraph tracing](langchain-langgraph-tracing.md)
and [OpenTelemetry tracing](opentelemetry-tracing.md).

## Record an external execution

Use the existing `SentinelClient` to register an agent, save an immutable version
with the default `external_agent` alias, and create a run. Keep the returned run ID.
Then wrap your own execution with a fresh recorder for that run and thread:

```python
from sentinel.trace_recorder import TraceRecorder

recorder = TraceRecorder(source="my_python_agent")
with recorder.span("agent.run"):
    with recorder.span("model.generate", "model") as span:
        result = my_agent_call()  # Your code and provider; Sentinel does not call it.
        # Supply real provider usage only if available; otherwise leave it unknown.
        # span.update(input_tokens=actual_input_tokens, output_tokens=actual_output_tokens)

evidence = recorder.finish(
    {"answer": result},  # Explicit, sanitized JSON output; no credentials/private data.
    reported_status="succeeded",
    idempotency_key="stable-final-trace-0001",
)
receipt = client.submit_external_trace(run_id, evidence)
summary = client.external_trace(run_id)
output = client.external_trace(run_id, include_output=True)
```

The final output must be a JSON object. `finish` validates evidence and can be
called only once after all spans close. Keep its returned payload for replay
after a timeout; do not remeasure execution or generate another key. The recorder
retains operation names, nesting, durations and explicitly supplied model token
counts. It does not capture prompts, tool arguments/results or exception text.
Exceptions mark their span failed and are re-raised; your caller decides the
final reported outcome and any sanitized failure output.

## API and trust boundary

- `POST /v1/runs/{run_id}/external-trace`: admin/developer/worker; 201 for new
  evidence, 200 for matching replay, 409 for a conflicting finalized report.
- `GET /v1/runs/{run_id}/external-trace`: admin/developer/reviewer/worker;
  submitted output omitted by default. Use `?include_output=true` to retrieve it.
- One finalized trace per run, with organization-scoped lookup and a canonical
  content hash. Replay compares normalized evidence, not JSON whitespace/key order.
- The run needs neutral external-agent metadata or a nonempty external workflow
  marker; explicit `estateflow` runs cannot attach these reports.
- At most 100 spans and 64 KiB of canonical UTF-8 evidence; transport is bounded
  at 128 KiB before parsing, including chunked bodies. Span IDs are unique;
  parents must exist, be acyclic, and contain their children's timing interval.
- Unknown token counts remain unknown. Supplied usage covers only reported model
  spans; it never proves that all external activity was captured.

Reports are explicitly `caller_reported` and are not governed execution proof.
Ingestion does not execute actions, consume approvals, alter Sentinel tool/model
ledgers or change run status. Reported outcome and governed run status can differ.
Existing eligible-run closure remains a separate admin/worker operation; it does
not verify external output correctness. Current ledger-based evaluations do not
add their tokens to governed budgets. Explicit `output_equals` and `output_schema`
requirements now score finalized external outputs; see the
[output evaluation guide](output-evaluations.md). These checks do not judge prose
truth or verify authorized execution. Required, ordered and forbidden operation
paths plus reported execution budgets can be checked with the
[trajectory evaluation guide](trajectory-evaluations.md).

The dashboard's saved-run buttons open an inspector for this evidence. Authorized
users can paste finalized JSON and explicitly reveal output as text. Default
timelines contain only the value-free `external_trace.recorded` event; prompts,
outputs and event details remain omitted.

This API stores the output you explicitly submit. It does not automatically find
or redact secrets in it. Submit sanitized data; authorized organization keys and
database backups can access stored evidence. Internet hosting, retention/deletion
policies, independent installation, live trials and browser QA remain open.

## Verification

Run `python -m unittest discover -s tests -p test_external_traces.py` and
`python tests/acceptance_external_traces.py` with the project virtual environment.
Acceptance uses native PostgreSQL and synthetic support/code-analysis fixtures,
plus a real local compiled LangGraph invocation, including concurrent replay,
privacy defaults, transport limits, tenant/role boundaries and unchanged governed
ledgers. The local graph has no hosted model or external tools and is not a live AI trial.
The sequential native/full release profiles now include this acceptance stage.
