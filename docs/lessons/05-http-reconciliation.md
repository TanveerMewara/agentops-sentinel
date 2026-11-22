# Lesson 5: Connect decision rules to real HTTP evidence

## What we are building now

Lesson 4 supplied fictional events to a state machine. This lesson connects those
rules to a running booking service through HTTP. It is our first small execution
and reconciliation loop, not the complete Sentinel platform.

The loop is: submit once -> receive a timeout -> record UNKNOWN -> look up that
operation -> record SUCCEEDED if the evidence matches, otherwise NEEDS_REVIEW.

PostgreSQL verification from Lesson 3 is still blocked by Docker's engine error.
This lesson is independent: both the external service and Sentinel's state use
memory. It does not implement durable recovery or a persisted execution ledger.

## Three responsibilities

1. The booking service creates appointments and can return a receipt for a specific
   operation ID. It owns the actual appointment.
2. The adapter knows this service's HTTP format and checks its receipts.
3. The decision rules decide which state transition is allowed.

An adapter is a small translator for one external system. Reconciliation means
checking what happened after an uncertain outcome. A receipt is the returned
operation ID, booking ID, customer, and slot. Here the service is trusted and local;
matching fields alone would not authenticate an untrusted remote service.

No new third-party technology is introduced. We reuse Python, HTTP, JSON, FastAPI,
and Uvicorn, plus the state machine from Lesson 4.

## Run with two terminals

From C:\AgentOps Sentinel, in terminal A:

```powershell
.\.venv\Scripts\python.exe -m uvicorn lessons.reconciliation_service:app --host 127.0.0.1 --port 8002
```

In terminal B:

```powershell
.\.venv\Scripts\python.exe -m lessons.05_reconcile_booking
```

The -m option loads the file as a module within lessons, so it can reuse sibling
modules. Keep terminal A running while you run the client.

Expected: READY -> EXECUTING -> UNKNOWN -> SUCCEEDED, with one submission and one
read-only lookup. The server saves the appointment before delaying the response for
two seconds. The client stops waiting after half a second, then asks for the result.
The second request is GET, not another POST.

Now model an adapter without trustworthy lookup support:

```powershell
.\.venv\Scripts\python.exe -m lessons.05_reconcile_booking --no-lookup
```

Expected: NEEDS_REVIEW, with one submission and zero lookups. The same lab server
still has lookup capability; the flag deliberately disables its use in this adapter
so we can demonstrate the conservative policy for a service without it.
Each command creates a new fictional intended action with a fresh operation ID.

Open http://127.0.0.1:8002/docs to inspect endpoints. GET /bookings shows what was
actually created. Stop the server with Ctrl+C when finished.

## Read the service first

Open lessons/reconciliation_service.py.

- We reuse Lesson 2's app and booking function. Importing does not start a server.
  The added routes exist in this process; the original Lesson 2 file stays intact.
- OperationRequest requires an operation ID; this request cannot omit it.
- POST /operations calls the existing booking function and includes the operation
  ID in its returned receipt.
- GET /operations/{operation_id} reads the operation dictionary without creating
  anything. Missing results produce HTTP 404.

The service writes the booking and operation record before awaiting the delayed
reply. That lets a later lookup find the booking while the first reply is delayed.

## Then read the adapter and execution loop

Open lessons/05_reconcile_booking.py.

- importlib imports our numbered Lesson 4 module and reuses its rules.
- Action is an immutable record identifying the intended booking and its details.
- BookingAdapter.request sends JSON over HTTP using Python's urllib. It expects
  status 200. Its counters count submit and lookup method calls in this run; they
  are teaching instrumentation, not a durable audit log.
- submit makes one POST with a short client timeout.
- lookup makes a GET using the operation ID. quote safely encodes that ID for a URL.
- confirmed_booking checks that operation ID, customer, and slot exactly match the
  request and that the booking ID is nonempty. Unexpected evidence is rejected.
- execute_once enters EXECUTING, submits, and accepts a valid direct receipt. After
  a timeout it enters UNKNOWN. Other transport, HTTP, or malformed-response errors
  also enter UNKNOWN using the new OUTCOME_UNCERTAIN event.
- It then tries one lookup. A trustworthy matching receipt confirms success;
  unavailable lookup, HTTP errors, malformed results, or mismatches require review.

There is deliberately only one call to submit in execute_once. That is a property
of one invocation, not protection against process restarts, multiple callers, or
running the function again. Persistent operation ownership comes later.

## Why not declare failure after a 404 or 500?

A lookup can report no result while an original request is still running. Some
services also delay visibility of completed results. Absence is not enough proof
that nothing happened or that the original request cannot still finish.

A server error can also happen after a write. Our initial policy treats these
responses conservatively. Later adapters may recognize a documented rejection
that guarantees no effect, but we will not infer that from a generic HTTP error.

This lesson makes one lookup, then escalates. It does not implement repeated lookup,
backoff, reconciliation queues, approval, or human resolution. Conservative review
may reduce completion; future evaluations must measure that tradeoff.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite starts its own local server on an available port and stops only that
process afterward. Seven new checks cover real delayed HTTP responses, immediate
success, disabled lookup, mismatched receipts, missing lookup results, unusable
submission receipts, and checking all requested fields. Some negative cases use
adapter subclasses to alter real service evidence deliberately; they are labeled
in the tests. The earlier six state tests also run.

The evidence shows the in-memory HTTP flow, not PostgreSQL or production readiness.

## Understanding checkpoint

In the timeout scenario, find the POST and the later GET in the code. Explain why
GET is the useful next operation here. Then explain why the service can contain a
booking even when Sentinel ends in NEEDS_REVIEW.

Next, we need to verify PostgreSQL and persist the operation lifecycle before we
can claim this loop survives crashes. The broader tracing, evaluation, security,
approval, MCP, and EstateFlow scope remains unchanged.
