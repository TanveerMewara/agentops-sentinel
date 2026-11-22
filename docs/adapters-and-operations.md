# Adapter runtime and operational guardrails

## Installed code and registered contracts

Tool registration creates a versioned contract and permissions; it never installs
Python code. A deployment owner installs a `ToolAdapter` in an `AdapterRegistry`
and passes that registry to `create_app(settings, adapters=registry)`.

Custom adapters match the exact name, version, input schema, output schema, risk,
and approval mode installed by the owner. Changing any of these requires a new
installation. Description changes do not change execution semantics. The built-in
booking bridge reserves `book_viewing` versions 1.0.0 and 2.0.0 with high risk and
mandatory approval; its service-specific receipt validation remains in place.
Custom adapters cannot replace that reserved name.

The server supplies `AdapterContext`: organization, run ID, tool-call ID, a copy
of approved arguments, and a copy of the frozen contract. The adapter returns
`AdapterResult(external_id, result)`. Sentinel validates the output against the
frozen schema and retains its existing approval, lease, budget, fencing, and
append-only event controls. Worker discovery includes matching installed custom
contracts; an unsupported contract fails before approval consumption or execution.

`execute` must use the tool-call ID as the external idempotency identity.
`reconcile` must only inspect durable evidence, verify organization and arguments,
and return an outcome it can prove. A missing receipt does not authorize a retry.
Unexpected adapter exceptions become sanitized uncertain outcomes, since a write
may already have committed. Invalid output becomes a human-review outcome.

These adapter obligations are trusted deployment code, not a sandbox enforced by
Python. Schema validation alone cannot prove external business facts or force an
arbitrary adapter to reconcile without writing. Review every installed adapter's
authorization, endpoint configuration, evidence checks, and credential handling.

## Durable second adapter example

The reference booking adapter also uses a [process-local outage circuit](provider-circuit.md).
The runtime checks its availability before consuming approval and checks again
before the booking write. Read-only reconciliation remains available. The registry
supports an optional deployment-installed `prepare_execution()` hook before claim;
this hook must only check availability and must not perform business writes.
Custom adapter circuit policies remain the deployment owner's responsibility.

`examples/support_ticket_adapter.py` supplies a local SQLite support-ticket sandbox.
It stores one receipt per tool-call ID with organization and argument fingerprint.
Read-only reconciliation validates those fields. A test option loses the reply
after committing, allowing recovery without another write. SQLite receipts survive
recreating the adapter process while the file remains available.

Install it from deployment code, using an owner-selected path:

```python
from pathlib import Path
from sentinel.adapters import AdapterRegistry
from sentinel.booking_adapter import BookingAdapter
from examples.support_ticket_adapter import CONTRACT, SupportTicketAdapter

registry = AdapterRegistry(BookingAdapter(settings.booking_service_url))
registry.install(CONTRACT, SupportTicketAdapter(Path(".local/support-tickets.sqlite")))
app = create_app(settings, adapters=registry)
```

The example is repository source; the packaged Sentinel module does not ship an
`examples` package. Import it from a repository checkout or copy the adapter into
your deployment package. The selected file's parent must exist. This is a durable
local sandbox, not an external CRM/calendar integration or multi-host SQLite
deployment. The default application installs the booking bridge and the
[native calendar adapters](native-calendar.md); this
example's installation is explicitly supplied to the application factory.

## Shared API request limits

Each valid API key defaults to 600 authenticated requests per 60-second fixed
window. `SENTINEL_REQUESTS_PER_WINDOW` accepts 1–100000 and
`SENTINEL_REQUEST_WINDOW_SECONDS` accepts 1–3600. All API replicas must use the
same policy. Authentication takes a PostgreSQL row lock and reads database time
after locking, so concurrent replicas share one admission counter. A 429 response
includes `Retry-After`. Block counters commit even when the request is rejected.

Counters are per key, not per organization or IP. Invalid credentials, health
checks, and pre-authentication traffic need an additional reverse-proxy limit.
Fixed windows permit bursts around a boundary; this is not a sliding-window or
token-bucket guarantee. Database unavailability fails requests rather than allowing
unlimited traffic. Authentication now adds database work; hosted throughput and
connection pooling still need measurement. Read-only work can wait and retry;
external writes must retain their explicit idempotency/reconciliation behavior.

## Operations pulse

`GET /v1/operations/overview` is available to admins, developers, and reviewers.
Its consistent read-only snapshot includes pending approvals, authorized calls,
uncertain outcomes, expired execution leases, completed calls, run status counts,
active/soon-expiring keys, cumulative request-limit blocks, and installed adapter
names/versions. Arguments, contacts, inputs, tokens, credential digests, and raw
event payloads are omitted. Counts are tenant-scoped; installed adapter metadata
describes deployment capabilities and does not grant access to them.

The dashboard's Operations pulse panel displays these signals with refresh and
connection/role guidance. An authorized call is not necessarily executable if its
adapter is absent. Expired-lease counts are signals for recovery, not evidence of
a running worker. There is no fabricated health percentage or hosted monitoring
claim. Production user sign-in, alerts, OpenTelemetry, and hosted checks remain.

## Native acceptance

```powershell
.\.venv\Scripts\python.exe tests/acceptance_adapters_limits.py
.\.venv\Scripts\python.exe tests/integration_api.py
.\.venv\Scripts\python.exe tests/acceptance_migrations.py
```

The first script verifies exact installation, approval, two concurrent execution
requests with one successful claim, a lost reply after commit followed by
evidence-only recovery through a recreated adapter, tampered-evidence rejection,
and unsupported version denial. Twenty requests across
two API instances admit exactly five and reject fifteen using a dedicated test
key. It checks committed block counts, window reset, independent keys, and
cross-tenant operational-counter isolation. Temporary keys are revoked and the
SQLite fixture is removed. Synthetic runs remain in the native test database.
The existing integration suite checks the default booking/workflow paths.

Sentinel schema migrations also take a transaction-scoped PostgreSQL advisory
lock before reading applied versions. The migration acceptance script creates its
own temporary database and starts two migration callers concurrently. Both must
finish with all 18 versions recorded exactly once, and replay must be idempotent.
Cleanup targets only the uniquely named database created by that script. This
tests Sentinel's schema migrations, not every third-party startup routine.

All of this runs with native PostgreSQL, Python, and project-local Node. Docker,
external accounts, paid model calls, and actual customer messages are unnecessary.
