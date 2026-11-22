# OpenTelemetry trace import

`otlp_json_to_external_trace` converts one trace from an OpenTelemetry OTLP/JSON
`ExportTraceServiceRequest` into Sentinel's validated external evidence format.
Use it locally, through Sentinel's run-scoped managed import endpoint, or configure
an OTLP/HTTP exporter to send the standard request body directly to Sentinel's
authenticated `/v1/traces` receiver.

```python
from sentinel.integrations.otlp_trace import otlp_json_to_external_trace

evidence = otlp_json_to_external_trace(
    otlp_export,
    {"answer": sanitized_answer},
    trace_id="5b8efff798038103d269b633813fc60c",  # needed for multi-trace exports
    source="opentelemetry",
    idempotency_key="support-run-0001-otlp",
)
client.submit_external_trace(run_id, evidence)
```

For server-side conversion, the Python client builds the strict request wrapper:

```python
receipt = client.submit_otlp_trace(
    run_id,
    otlp_export,
    {"answer": sanitized_answer},
    "support-run-0001-otlp",
    trace_id="5b8efff798038103d269b633813fc60c",
)
```

This calls `POST /v1/runs/{run_id}/external-trace/otlp`. Admin, developer and
worker keys may import; reviewer keys cannot. New evidence returns 201, exact
concurrent/idempotent replay returns 200, and different evidence for the finalized
run returns 409. Reads continue through the existing external-trace endpoint and
hide output unless `include_output=true` is explicitly requested. The request is
limited to 128 KiB before JSON parsing.

## Standard OTLP/HTTP receiver

Configure the exporter endpoint as `https://YOUR-SENTINEL/v1/traces` with these
headers:

- `X-API-Key`: an admin, developer or worker Sentinel service key.
- `X-Sentinel-Run-Id`: the UUID of the already-created external-agent run.
- `X-Sentinel-Trace-Id`: optional 32-character hexadecimal selection when the
  export contains more than one trace.
- `X-Sentinel-Source`: optional lowercase source identifier; defaults to
  `opentelemetry`.

The body is an OTLP `ExportTraceServiceRequest` encoded as JSON or binary Protobuf.
It may use `Content-Encoding: gzip`. A new or matching replay returns HTTP 200 with
the matching OTLP response encoding: `{}` for JSON or an empty serialized
`ExportTraceServiceResponse` for Protobuf. Metrics/logs, cost/completeness and
lifecycle controls are documented in [Stage 3 telemetry](stage-3-telemetry.md).

Receipt is intentionally separate from agent-result finalization. `/v1/traces`
stores an immutable privacy-filtered pending trace and records a value-free
`external_trace.otlp_received` event. It does not create evaluable external evidence
or invent an empty output. After the agent finishes, finalize with sanitized output:

```python
receipt = client.finalize_otlp_trace(
    run_id,
    {"answer": sanitized_answer},
    "support-run-0001-final",
    reported_status="succeeded",
)
```

This calls `POST /v1/runs/{run_id}/external-trace/otlp/finalize`. New final evidence
returns 201 and exact concurrent replay returns 200. Before finalization, normal
external-trace reads and evaluations cannot see the pending trace. After finalization,
later exporter writes conflict instead of changing the saved evidence.

The converter follows the official OTLP/JSON shape and encoding: `resourceSpans`,
`scopeSpans`, lower-camel-case fields, hexadecimal trace/span IDs and decimal-string
nanosecond timestamps. See the [OTLP specification](https://github.com/open-telemetry/opentelemetry-proto/blob/main/docs/specification.md)
and [official trace JSON example](https://github.com/open-telemetry/opentelemetry-proto/blob/main/examples/trace.json).

## Mapping

The converter uses `gen_ai.operation.name`, `gen_ai.tool.name`,
`gen_ai.workflow.name`, `gen_ai.usage.input_tokens` and
`gen_ai.usage.output_tokens`. It also recognizes the common
`openinference.span.kind` values for LLM, embedding, tool, retrieval and agent spans.
Operation names become the same bounded `agent.*`, `model.*`, `tool.*` and
`retrieval.*` identifiers used by trajectory evaluation.

OpenTelemetry's GenAI conventions are still marked development. A producer upgrade
can therefore require a Sentinel adapter update. The relevant upstream references
are the [GenAI span conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md)
and [GenAI attribute registry](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/gen-ai.md).

## Privacy and validation

Sentinel reads only structural IDs/timestamps, selected operation-name attributes,
error status and aggregate token totals. It ignores resources, instrumentation
scope details, events, links, status messages and every other attribute. In
particular it does not retain `gen_ai.input.messages`, `gen_ai.output.messages`,
system instructions, model identifiers, tool arguments/results or exception text.
The sanitized final output remains an explicit caller choice.

One call converts exactly one trace. If an export contains more than one trace,
pass its 32-character hexadecimal trace ID. The import scans at most 1,000 spans
and the selected trace may contain at most 100. IDs, timestamps, duplicate
attributes, exact nanosecond tree containment, cycles, normalized duration, JSON
output and the 64 KiB final evidence size are validated before submission.

Missing token totals remain unknown. Both input and output totals must be present
and valid for a model span before either is recorded. External parents absent from
the selected export are detached rather than invented.

OTLP conversion remains caller-reported evidence. It does not prove that telemetry
was complete, unmodified or connected to authorized external actions. Sentinel now
accepts JSON/Protobuf and gzip for trace, metric and log signals, but remains a
run-correlated AgentOps receiver rather than a general telemetry lake. Signed
provenance and live outside-application trials remain operational work.

`tests/test_otlp_trace.py` covers semantic mapping, usage, status, hierarchy,
multiple traces, privacy, limits and malformed data. The native PostgreSQL external
trace acceptance sends a standard body to `/v1/traces`, confirms it is unavailable
before explicit finalization, and verifies roles, concurrent receipt/finalization,
transport limits, conflicts, tenant isolation, ledger separation and that sensitive
GenAI attributes never enter the stored evidence view.
