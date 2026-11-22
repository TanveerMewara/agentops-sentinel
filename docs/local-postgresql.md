# Native PostgreSQL for local development

We use real PostgreSQL directly on Windows. Docker is optional for this setup and
remains planned for later application packaging. This setup is local development,
not a production database deployment.

## Why this matters

The database is the durable memory of our system. A Python dictionary disappears
with its process; committed PostgreSQL records should survive ordinary API and
database restarts. We verify this behaviour rather than infer it from using a database.

## What the setup contains

- Official PostgreSQL 17.11 Windows binaries from EDB, linked by PostgreSQL's site.
- .local/pgsql: database programs, not application code.
- .local/postgres-data: the project database files. Do not delete this to restart.
- .local/postgres-config.json: generated development passwords, excluded from Git.
- .local/postgres.log: server startup and diagnostic output.
- A loopback-only listener at 127.0.0.1:55432.
- A bootstrap administrator and a non-superuser lesson account.

The lesson account owns its development database so it can create the teaching
schema. Production will separate migration privileges from runtime privileges.
Ignored files are not encrypted; use a private machine account and do not share
.local or its credentials. Backup policy is separate from keeping a local directory.

## Repeat setup on another Windows machine

Install Python 3.11 or newer, create .venv, and install requirements.txt as in
Lesson 2. Download the archive linked by the official Windows page:

https://www.postgresql.org/download/windows/
https://www.enterprisedb.com/download-postgresql-binaries

Our selected archive is:
https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip

Save it as .local/postgresql-17.11.zip. Then run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts/native_postgres.py setup
```

The script extracts binaries, initializes a new cluster only if absent, generates
passwords once, and starts the project database. A cluster is PostgreSQL's directory
of databases and server settings. initdb prepares it; pg_ctl starts/stops the server.
The script validates archive extraction paths and never removes a database directory.
It does not install a Windows service or automatically start after Windows reboot.
The official archive is downloaded over HTTPS; a recorded local hash is provenance,
not independent publisher signature verification.

## Everyday commands

```powershell
.\.venv\Scripts\python.exe scripts/native_postgres.py status
.\.venv\Scripts\python.exe scripts/native_postgres.py start
.\.venv\Scripts\python.exe scripts/native_postgres.py check
.\.venv\Scripts\python.exe scripts/native_postgres.py serve
```

serve runs the persistent lesson API at http://127.0.0.1:8001/docs. In another terminal:

```powershell
.\.venv\Scripts\python.exe lessons/02_http_client.py --base-url http://127.0.0.1:8001
```

Stop the API with Ctrl+C. Stop PostgreSQL when finished with:

```powershell
.\.venv\Scripts\python.exe scripts/native_postgres.py stop
```

check runs only against this project-local database and restarts that database to
verify persistence. Run it while no other lesson user depends on this development
instance. Successful fictional test bookings remain for inspection.

## Where the password goes

The launcher reads local configuration and supplies the connection settings through
SENTINEL_LESSON_DATABASE_URL for the child Python process. It does not print the
password or require pasting it into chat. The old public Docker lesson password is
not used for this native instance.

## Product standard

A working local database is one prerequisite, not production readiness. Before an
external pilot, we still need authenticated tenant isolation, migrations, durable
operation ownership, approval enforcement, a safe configuration path without lesson
defaults, redaction, bounded workloads, backup/restore verification, deployment and
monitoring, and onboarding exercised by someone other than the author.
