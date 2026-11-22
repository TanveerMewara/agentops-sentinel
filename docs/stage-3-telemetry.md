# Stage 3: production OTLP telemetry

Stage 3 gives external agents one authenticated, run-correlated OTLP/HTTP boundary
for traces, metrics and logs:

- `POST /v1/traces`
- `POST /v1/metrics`
- `POST /v1/logs`

Every request requires `X-API-Key` and `X-Sentinel-Run-Id`. Trace requests may
also use `X-Sentinel-Trace-Id` to select one trace and `X-Sentinel-Source` to set
the normalized source. Admin, developer and worker keys can write telemetry;
reviewers have read access to the run summary only.

## Wire formats and limits

All three endpoints accept `application/json` and `application/x-protobuf`.
`Content-Encoding` may be `identity` or `gzip`. A successful response uses the
same media type as the request: `{}` for JSON and a serialized empty OTLP export
response for Protobuf. Binary Protobuf is the normal OpenTelemetry SDK default.

The compressed HTTP body is limited to 1 MiB. The decoded body is limited to
4 MiB, including gzip expansion. Metric and log requests may contain at most
10,000 data points or records. Oversized transport or decoded content returns 413;
unsupported media/encoding returns 415; malformed encoding returns 400; structurally
unsafe telemetry returns 422. Exporter batch sizes must respect these product limits.

This release implements OTLP/HTTP. It does not expose OTLP/gRPC or profiles.

## Stored evidence

Trace receipt keeps the existing two-phase rule. `/v1/traces` stores a bounded,
privacy-filtered pending trace. The agent then calls the finalization API with its
sanitized output and reported status. Until finalization, normal external-trace
reads and evaluations cannot treat the trace as complete agent evidence.

Metric receipt stores only normalized aggregate evidence:

- input/output token totals from `gen_ai.client.token.usage` or
  `gen_ai.server.token.usage`;
- model duration from `gen_ai.client.operation.duration` or
  `gen_ai.server.request.duration`;
- tool duration from `gen_ai.tool.call.duration`;
- retrieval duration from `gen_ai.retrieval.duration`;
- item counts, selected rate-card versions and estimated USD cost.

Durations use the OTLP metric unit expected by the GenAI conventions and are
normalized to milliseconds. Sentinel does not persist arbitrary metric names,
resources or attributes.

Log receipt stores total count, severity counts and the number of distinct
correlated trace IDs. Every log body, attribute, resource and scope value is
discarded before persistence. Sentinel provides health counts rather than log
search in this stage.

## Versioned cost calculation

An administrator creates an organization rate-card version:

```http
POST /v1/telemetry/rate-cards
{
  "pricing_key": "model.standard",
  "input_usd_per_million": "1.00000000",
  "output_usd_per_million": "2.00000000"
}
```

Each create appends the next version. A token point opts into a rate with
`sentinel.pricing.key=model.standard`. Sentinel uses the latest version when the
batch is accepted and records that version. It does not infer a price from provider
or model names, fetch changing public prices, or retroactively reprice batches.
Tokens without a recognized pricing key remain usage and add no estimated cost.

## Completeness and retention

An administrator controls the organization policy:

```http
PUT /v1/telemetry/policy
{
  "retention_days": 30,
  "required_signals": ["traces", "metrics", "logs"],
  "require_token_usage": true,
  "require_cost": true
}
```

`GET /v1/runs/{run_id}/telemetry` compares received evidence with that policy. It
returns `complete`, explicit `gaps`, present signals, batch count, reported tokens,
estimated cost and privacy flags. Completeness means the declared policy is
satisfied by caller-reported telemetry. It does not prove that an exporter captured
every action or that reported values are truthful.

Normalized metric/log batches and pending trace receipts get an expiry at ingest.
New ingestion opportunistically removes expired metric/log batches. Administrators
can call `POST /v1/telemetry/retention/purge` for deterministic scheduled cleanup
and `DELETE /v1/runs/{run_id}/telemetry` for run-level deletion. Run deletion removes
normalized batches and a pending trace, records an audit event, and never deletes
finalized external evidence. A deployment should schedule the purge endpoint;
Sentinel does not install a Windows scheduler.

## Privacy and trust boundary

The receiver never stores raw metric payloads or raw logs. Trace conversion omits
prompts, responses, model identifiers, tool arguments/results, documents, events,
links, status text and unrecognized attributes. Content hashes provide idempotent
batch replay without retaining the source body. Rows are bound to both run and
organization, with standard service-key role and tenant checks.

This remains caller-reported observability. It does not convert an external tool
action into governed execution proof. Finalized external evidence stays immutable
and separate from Sentinel's internal tool/model ledgers.

Stage 3 acceptance sends a binary Protobuf trace and metric batch plus a gzipped
JSON log batch through the real API/PostgreSQL path. It verifies replay, privacy,
versioned cost, completeness gaps, role denial, expiry purge and run deletion.
