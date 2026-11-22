# Lesson 7 prerequisite: recover the database environment

Status: blocked before application consolidation. The teaching components remain
available, but PostgreSQL integration has not passed and no durable runtime is claimed.

## What the environment check found

- Docker Desktop processes exist, but the Docker engine returned HTTP 500.
- WSL listed docker-desktop as Stopped.
- Starting that WSL environment directly did not complete within 30 seconds.
- A prior bounded Docker Desktop restart also failed.

A running desktop window is not the same as a working Docker engine. WSL is the
Linux environment Docker uses here; PostgreSQL's container cannot run until that
underlying environment and engine are ready. This is an environment problem, not
proof that the Python booking logic is incorrect or correct.

Run the read-only diagnostic from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/check_environment.py
```

It checks WSL and Docker with bounded waits. It does not restart anything, alter
settings, reset Docker, or delete data. Permission-denied errors from an agent's
sandbox are different from the engine failure seen with elevated read access.

## Next recovery step

Open Docker Desktop and inspect its displayed startup/error status. Record the exact
message so we can diagnose the cause before changing Windows settings. Do not use
factory reset or delete Docker volumes as a troubleshooting shortcut.

Once the engine responds, run:

```powershell
docker compose up -d --wait --wait-timeout 60
.\.venv\Scripts\python.exe lessons/03_persistence_checks.py
```

We must verify the delayed response, API restart, eight simultaneous requests, and
transaction rollback before marking persistence complete. Then we can consolidate
shared application modules and begin a persistent operation ledger. Repeatedly
adding independent demos would not satisfy this milestone.
