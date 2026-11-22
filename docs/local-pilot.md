# Local pilot, without Docker

The selected first launch is on your laptop. PostgreSQL stays native; Python runs
in `.venv`; the compiled dashboard runs with Node. This pilot demonstrates the
implemented platform using fictional bookings. It does not provide live calendar,
external CRM, or email delivery, and it does not finish the broader product scope.

## Verify and launch

With Python dependencies, project-local PostgreSQL, Node, and frontend dependencies
already installed, run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\release_check.py --profile full
.\.venv\Scripts\python.exe scripts\pilot.py --demo --api-port 8020 --booking-port 8022 --web-port 3020
```

The full profile runs unit tests, frontend types/lint/build, migration concurrency,
custom adapters and shared limits, native calendar, website enquiries, access/client integration,
saved-run evaluations, stdio MCP, real API recovery, compiled pilot startup, and
backup restoration. Stages run sequentially. The first failure stops the run; later
stages are marked `not_run`. The report is written atomically to ignored
`.local/release-checks/latest.json`. Reports contain stage metadata rather than raw
test output or keys. Rerun the failing stage's command from the README for details.

To keep the compiled local product running in the background after validation:

```powershell
.\.venv\Scripts\python.exe scripts\local_service.py start --demo
.\.venv\Scripts\python.exe scripts\local_service.py status
.\.venv\Scripts\python.exe scripts\local_service.py stop
```

`--profile unit` checks only unit tests. `--profile native` checks unit tests and
native database/API acceptance without building or starting the dashboard.
A passing profile certifies only the checks included in that invocation. It does
not certify an earlier report, later edits, other machines, or production readiness.
Reports are local files rather than signed independent attestations.

`--demo` installs a fictional reference agent/version, a property-bound booking
grant limited to one call per run, and a Jaipur metro listing. It does not create
buyers, approve actions, book viewings, or send messages. Repeating setup reuses
its identities. An incompatible existing booking contract is rejected rather than
overwritten. Omit `--demo` when using your own configuration.

The launcher starts the booking service on `127.0.0.1:8002`, the Sentinel API on
`127.0.0.1:8000`, the compiled dashboard on `127.0.0.1:3000`, then the worker.
It checks real health endpoints and authenticated identity first. Backend secrets
are not inherited by frontend tooling. All services bind to loopback; this does
not expose a public site or allow friends to connect over the internet.

The launch command above uses alternate ports so it can coexist with your earlier
development services. Open `http://127.0.0.1:3020` and use **Connect API** with
`http://127.0.0.1:8020`. Without port options, the launcher uses the defaults above.
Display local keys separately with:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py show-keys
```

Keep these keys private. Use developer access for lead intake and run creation,
reviewer access for human decisions, and administrator access for key management.
The worker uses its own configured key. The sidebar moves between the implemented
panels; the operation approvals shortcut filters the operation queue.

Press Ctrl+C in the launcher's terminal to stop the processes it started.
PostgreSQL stays running. Existing services are never adopted or stopped: a busy
port causes startup to fail. Use the launcher's `--api-port`, `--booking-port`, and
`--web-port` options if another local process needs the default ports. Enter the
matching API URL when connecting the dashboard.

For a startup check that stops immediately after dashboard readiness and identity
verification, without dispatching worker actions:

```powershell
.\.venv\Scripts\python.exe scripts\pilot.py --check --api-port 8020 --booking-port 8022 --web-port 3020
```

To explore the dashboard with automatic worker dispatch paused, keep a preview
session running:

```powershell
.\.venv\Scripts\python.exe scripts\pilot.py --demo --preview --api-port 8020 --booking-port 8022 --web-port 3020
```

Preview starts the dashboard, API, and booking sandbox. API actions remain available;
the automatic worker is not started. Omit `--preview` when you want the worker to
process approved actions during the local pilot.

The launcher suppresses component output to avoid collecting sensitive payloads.
If a component fails, run its individual command from the native release runbook
to investigate. Native acceptance creates fictional records in the local database.

## First pilot session

For the native scheduling path, first offer a future property slot in **Viewing
calendar**, then use **Leads → Arrange viewing → Native viewing calendar** and
enable its dedicated agent. See [native workflow](native-calendar.md#automatic-lead-bound-native-workflow)
for review, dispatch, cancellation and preview-mode instructions. The reference
booking session below remains separately supported and fictional.

1. Connect with developer access and enter a fictional buyer enquiry in **Leads**.
   Check the qualification reasons and consent before launching a viewing run.
2. Use an agent/version with the property-bound booking tool and grant installed.
   Review the selected property citation and proposed viewing action.
3. Switch to reviewer access and approve the exact action. Let the worker execute.
   Confirm the booking receipt and timeline rather than treating approval as success.
4. Inspect the internal CRM projection and follow-up draft. Edit and approve a
   revision. Approval does not send an email.
5. Inspect run outcomes, saved-rule evaluations, and Operations pulse. With
   administrator access, inspect and revoke a temporary access key.
6. Record confusing steps, failures, elapsed time, and whether a developer would
   choose this tool for an actual workflow. Outside feedback remains pending until
   someone independently uses it.

The automated integration checks create their own configurations and exercise these
flows. With `--demo`, choose **EstateFlow local pilot**, version `1.0.0`; use a
fictional Jaipur buyer with a budget above INR 7,500,000 and search for `metro`.
Use the existing website-enquiry and booking guides for your own configuration;
API endpoints are documented at `http://127.0.0.1:8000/docs`.

The broader release still requires the missing features and evidence listed in
[project status](project-status.md). The ordered [release backlog](release-backlog.md)
states the pass conditions for the remaining local and full-product work.
A working local pilot is one release milestone.
