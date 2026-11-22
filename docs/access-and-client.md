# Access administration and independent agent integration

The dashboard's **Keys and permissions** panel identifies the connected organization
and role. Administrators can issue role-scoped keys, choose an optional expiration,
revoke keys, and inspect an audit trail. Other roles see their identity and access
boundary without loading administrator data.

## API key lifecycle

- `GET /v1/me`: current organization, role, and key ID.
- `GET /v1/access/keys`: administrator-only key metadata; no digest or plaintext token.
- `POST /v1/access/keys`: administrator-only issuance with label, role, optional
  timezone-aware future `expires_at`. Returns the token once with `Cache-Control: no-store`.
- `POST /v1/access/keys/{key_id}/revoke`: administrator-only, tenant-scoped revocation.
- `GET /v1/access/events`: administrator-only created/revoked audit entries.

Tokens are randomly generated. PostgreSQL stores an HMAC digest using the separately
held application pepper. Issuance returns plaintext once; listing and audit do not
return it. The dashboard keeps a newly issued token only in React memory until
dismissed or its identity context reloads. It does not place that token in browser
storage. Labels are user-supplied technical names, not a secret-redaction channel.

Expired/revoked keys fail authentication on subsequent requests. Admin mutations
serialize on the organization row and recheck the actor after acquiring the lock.
Competing revocations cannot remove both active administrators. The API refuses
to revoke the last currently active administrator key. This does not guarantee an
administrator remains after natural expiration; retain a protected recovery key.
Requests already performing other platform work are not retroactively cancelled.

There is no token recovery endpoint. After an issuance timeout, inspect the key list
and revoke the orphaned key before issuing another. Issuance is intentionally not
an idempotent token-replay API. Stage 5 adds invitation-based browser members,
server-side eight-hour sessions, password hashing, pre-authentication limits, strict
SameSite cookies and CSRF verification. Service keys remain integration credentials.
External SSO, organization quotas, a device/session management screen and audited
key recovery remain broader deployment work. See
[Stage 5 product operations](stage-5-product-operations.md).

## Python HTTP client

External-agent traces and explicitly submitted outputs are also supported through
`submit_external_trace`, `submit_otlp_trace`, `finalize_otlp_trace` and
`external_trace`. The OTLP methods support managed import or finalization after an
OTLP/HTTP exporter sends JSON or Protobuf, optionally gzip compressed, to the
authenticated trace, metric and log receivers. Client helpers `telemetry`,
`telemetry_policy`, `set_telemetry_policy`, `add_rate_card`,
`purge_expired_telemetry` and `delete_run_telemetry` manage the normalized evidence
and its lifecycle. See the
[external evidence guide](external-agent-traces.md) for the recorder, replay and
trust boundaries and [OpenTelemetry tracing](opentelemetry-tracing.md) for its
strict trace format and [Stage 3 telemetry](stage-3-telemetry.md) for the complete
receiver. These reports do not prove governed execution or correctness.

Runnable plain-Python, LangGraph and OpenAI Agents SDK integrations are documented
in [Stage 2 agent integrations](stage-2-agent-integrations.md). Each uses only the
public client/trace boundary; framework code does not enter Sentinel's core runtime.

`sentinel.client.SentinelClient` works with the existing editable package installation.
It registers agents/versions, creates idempotent runs, reserves tool calls, completes
eligible runs, reads identity/timelines/outcomes, and submits evaluations. Permissions,
schemas, budgets, approval, and tenant checks remain enforced by the server.

```python
from sentinel.client import SentinelClient

client = SentinelClient("http://127.0.0.1:8000", developer_api_key)
who = client.identity()
agent = client.register_agent("my_agent", "My independent agent")
version = client.create_version(agent["agent_id"], "1.0.0", "My versioned instructions")
run = client.create_run(version["agent_version_id"], "stable-task-0001", {"task": "example"})
```

The client requires HTTPS outside loopback, disables redirects and environment
proxies, omits credentials and response payloads from exception messages, and never
automatically retries writes. HTTP errors expose only a status (`SentinelError.status`).
Status 0 means an unresolved transport/response failure. Replay a write with its
original idempotency key or use server reconciliation; do not invent a new key after
a lost response. It is a synchronous client with bounded request timeouts, not a
durable queue, general external-adapter runtime, or complete enterprise SDK.

Stage 4 client helpers submit immutable human labels, calibrate a judge, analyze
repeated experiments, create release gates, configure online sampling and consider
terminal runs for sampling. The provider-backed experiment itself continues through
`evaluate`; advanced dataset fields are available through the HTTP dataset endpoint.
See [Stage 4 evaluations](stage-4-evaluations.md).

Stage 5 client helpers read/update alert policy, evaluate and acknowledge alerts,
manage deployment environments and gate-authorized deployment records, and queue,
claim and complete bounded lab campaigns. See
[Stage 5 product operations](stage-5-product-operations.md).

## Second independent agent example

`examples/support_triage_agent.py` is a separate deterministic, read-only support
classifier. It computes a queue/priority outside EstateFlow, registers a versioned
agent, records the classification in run input, and completes the run using a
separate organization worker key. It makes no model, booking, or email call.
Developer and worker identities must belong to the same organization.

With the local API running and environment credentials configured:

```powershell
.\.venv\Scripts\python.exe examples\support_triage_agent.py --key support-ticket-0001 --topic billing --severity high
```

Required environment variables are `SENTINEL_DEVELOPER_API_KEY` and
`SENTINEL_WORKER_API_KEY`; `SENTINEL_API_URL` defaults to local port 8000.
Replaying the same key and input returns the same completed run. This demonstrates
an independently implemented agent/client path. It does not prove outside-developer
installation, hosted execution, external result validation, or general tool adapters.

## Verification

Tool-schema errors retain HTTP 422 and the message/path/validation_error fields,
but use a root path and generic diagnostics. Rejected values and dynamic field
names are omitted. See the [threat model and security lab](threat-model.md).

The [native calendar desk](native-calendar.md#dashboard-workflow) has a separate,
purpose-limited developer proposal API. Reviewers approve/reject/revoke exact actions;
workers execute or recover receipts and can read its action queue. Workers cannot
read calendar slot/reservation listings or offer/propose/approve. The generic tool
reservation endpoint remains administrator/worker-only.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -q
.\.venv\Scripts\python.exe tests\acceptance_access_client.py
```

Native acceptance exercises real PostgreSQL and FastAPI with a client transport
bridged to TestClient. It verifies one-time issuance, digest storage, expiration,
revocation replay, audit, tenant isolation, concurrent admin protection, and client/
example replay with one ledger run and zero tool calls. Live-network/TLS and an
outside-developer quickstart remain additional release checks. Docker is excluded.
