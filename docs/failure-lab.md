# Local failure lab

Run from the repository root, without Docker, provider accounts, or PostgreSQL:

```powershell
.\.venv\Scripts\python.exe scripts\failure_lab.py
```

The command starts temporary loopback HTTP/TLS servers on automatically allocated
ports. It leaves the local pilot and its database alone. All buyer and receipt
data are fictional. Its exit code is nonzero if a check fails.

Five booking scenarios use real TCP connections. The fake provider saves exactly
one booking and closes the connection before replying. A newly created booking
client then reads that provider's receipt:

1. A matching receipt proves the booking succeeded.
2. Two temporary HTTP 503 responses precede a matching receipt; three reads recover
   it without another booking write.
3. Persistent HTTP 503 responses exhaust three reads and leave the result uncertain.
4. A missing receipt leaves the result uncertain, without another write.
5. A receipt for a different buyer raises an evidence mismatch, without another write.

Each scenario asserts exactly one POST, the expected number of GETs, and one saved
provider receipt. Recreating the client tests client-memory independence; the fake
provider remains alive in memory. This is not a provider process-restart or durable
storage test. Existing adapter tests separately exercise the SQLite sandbox.

The runner also includes booking retry/redirect checks, installed-adapter contract
checks, worker runtime checks, and real client/worker network and TLS checks.
The [booking circuit breaker](provider-circuit.md) checks cover admission before
approval consumption, bounded cooldowns, a single concurrent read-only probe,
recovery while dispatch is paused, invalid health evidence, and an actual HTTP
provider outage followed by health-probe recovery.
It saves `.local/failure-lab/latest.json` with a run identity, UTC completion time,
check count, status, and failed test identities. Tracebacks and provider payloads
are excluded from the report. For detailed diagnostics, run the relevant module:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_booking_failure_lab.py" -v
```

A passing lab is local regression evidence. It does not establish production
reliability, real provider compatibility, multi-host recovery, circuit breakers,
load capacity, prompt-injection resistance, or outside-user validation. Native API
acceptance and the broader release checklist remain separate checks.
