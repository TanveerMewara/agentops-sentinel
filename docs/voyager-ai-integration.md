# Voyager AI integration

This integration treats Voyager AI as an independently executed external agent.
Sentinel registers `voyager_ai`, creates immutable versions and runs, records a
privacy-minimal structural trace, stores a bounded response fingerprint, and closes
the run. Voyager continues to own travel reasoning and provider calls.

## Evidence boundary

Voyager request and response bodies are sent only between the adapter and Voyager.
Sentinel receives operation names, timings, status, response size, a SHA-256 response
fingerprint, an optional recommendation count, and a small allowlisted status. The
Voyager credential never enters a Sentinel request or report. A fingerprint proves
only byte-equivalent normalized JSON; it does not prove travel accuracy or safety.

## Required Voyager information

- A JSON/HTTP POST endpoint. Non-loopback endpoints must use HTTPS.
- Its authentication header, scheme and credential, if authentication is required.
- One representative JSON request that the endpoint accepts.
- Confirmation of the response keys containing itinerary/recommendation arrays.

The adapter accepts arbitrary JSON objects, but the example request is only a
placeholder and must be changed to Voyager's real contract.

## Run one connected execution

Start Sentinel, then load its ignored local keys without printing them:

```powershell
$config = Get-Content .local\sentinel-dev.json -Raw | ConvertFrom-Json
$env:SENTINEL_DEVELOPER_API_KEY = $config.keys.developer
$env:SENTINEL_WORKER_API_KEY = $config.keys.worker
$env:SENTINEL_API_URL = "http://127.0.0.1:8000"
$env:VOYAGER_API_URL = "https://your-voyager-host.example/v1/plan"
$env:VOYAGER_API_KEY = "your-private-key"

.\.venv\Scripts\python.exe examples\voyager_ai_agent.py `
  --request-file path\to\real-voyager-request.json `
  --key voyager-first-trial
```

If Voyager uses `X-API-Key` without a `Bearer` prefix:

```powershell
$env:VOYAGER_AUTH_HEADER = "X-API-Key"
$env:VOYAGER_AUTH_SCHEME = ""
```

Do not commit the real request or credential. Use synthetic traveler information
unless the environment has been reviewed for real personal data.

## Measure Sentinel performance with Voyager

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_voyager.py `
  --request-file path\to\real-voyager-request.json `
  --samples 10 `
  --warmups 1
```

The private report is written to `.local/voyager-benchmark/latest.json`. It includes:

- direct Voyager latency (P50/P95/P99 and mean);
- instrumented Voyager-call latency;
- the observed difference between those repeated-call distributions;
- Sentinel run-create, trace-submit and run-complete latency;
- monitored end-to-end latency and completed run count;
- the number of distinct normalized response fingerprints.

Direct and instrumented calls are alternating repeated requests, not the same
execution observed twice. Provider and network variability can dominate the delta.
The report describes only that endpoint, payload, machine, network and run. Sentinel
submission is out of the agent critical path unless the integration deliberately
waits for ingestion before returning to the Voyager user.

## Verified live connection

On 14 October 2026, the connector successfully called Voyager's deployed
`POST /api/plan` NDJSON stream, recorded a privacy-minimal Sentinel trace and
completed the run. The focused 3+3 live benchmark is summarized in
`reports/voyager-ai-sentinel-performance.md`. Treat it as small-sample integration
evidence, not a production SLA or travel-quality score.
