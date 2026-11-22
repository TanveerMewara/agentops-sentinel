# Native release and database recovery

The local release uses native PostgreSQL, Python's virtual environment, and Node.
Docker is excluded. Its automated release profile passes; local evidence is not a
hosted public-production claim.

## Local services

For a single compiled-pilot launcher, use [local pilot](local-pilot.md).
`scripts/pilot.py` starts the API, fictional booking service, dashboard, and worker
without Docker; Ctrl+C stops only its own components. The individual commands below
remain useful for development and diagnostics.

For background local operation with explicit component ownership:

```powershell
.\.venv\Scripts\python.exe scripts\local_service.py start --demo
.\.venv\Scripts\python.exe scripts\local_service.py status
.\.venv\Scripts\python.exe scripts\local_service.py stop
```

Run setup once, then launch the three services in separate terminals:

```powershell
.\.venv\Scripts\python.exe scripts\dev.py setup
.\.venv\Scripts\python.exe scripts\dev.py serve-api
.\.venv\Scripts\python.exe scripts\dev.py serve-booking
.\.venv\Scripts\python.exe scripts\dev.py serve-worker
```

Launch the frontend from `web` with the project-local Node directory on PATH and
`npm run dev`. `npm run build` and `npm run start` provide the compiled frontend.
The booking service is a fictional reference adapter. Configure an agent and tool
grant before creating a workflow run. The dashboard needs a local organization key;
do not publish a key in a public website or commit `.local`.

## Native backups

```powershell
.\.venv\Scripts\python.exe scripts\backup_database.py backup
.\.venv\Scripts\python.exe scripts\backup_database.py rehearse .local\backups\sentinel-ARCHIVE_ID.dump
.\.venv\Scripts\python.exe scripts\backup_database.py check
```

`backup` writes a custom-format database archive and a SHA-256/table-count manifest
inside ignored `.local/backups`. Counts and the dump share an exported repeatable-
read snapshot. This follows PostgreSQL's documented [pg_dump backup mechanism](https://www.postgresql.org/docs/17/app-pgdump.html).

`rehearse` accepts only an archive in that directory whose manifest checksum matches.
It creates a random temporary database, uses [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)
in a single transaction with error-stop enabled, checks all public table counts,
and checks encrypted lead decryption with the separately held application key.
Cleanup can drop only the database successfully created by this invocation.
`check` performs both operations. It never accepts an existing restoration target.

These are native development recovery checks. Archives contain database data,
including encrypted credentials, key digests, and any stored customer information;
they are sensitive files. The application encryption key, authentication pepper,
and API key files are not included. Preserve the matching key material separately
in protected storage. A database archive alone cannot recover encrypted contacts
or recreate user-held API tokens.

The rehearsal restores as the local database administrator with ownership/grants
excluded. It verifies data reconstruction and decryption, not production role
provisioning, full application restart, offsite retention, key recovery, or disaster
recovery on another machine. Managed-host restore, scheduled encrypted/offsite
backups, retention, least-privilege roles, and recovery-time targets remain open.

## Release checks

`scripts/release_check.py --profile full` runs the local checks sequentially and
saves an atomic metadata report in ignored `.local/release-checks/latest.json`.
Failures stop later stages. The report always distinguishes local checks from
production readiness. See the local pilot guide for profiles and launch commands.

Run focused tests, PostgreSQL/API acceptance, website acceptance, evaluation
acceptance, and frontend type/lint/build checks. Use a trusted evaluation report
with `scripts/evaluation_gate.py` for business-rule gates. The GitHub workflow is
configured but has not run remotely or been connected to actual deployment.

Before outside users: supply live integration credentials in a secrets service,
configure production identity and tenant onboarding, run actual workflow trials,
enable monitoring and alerts, test capacity and external-service ambiguity, rehearse
hosted restore, and obtain outside pilot feedback. These remain explicit release
criteria rather than tasks silently replaced by local fixtures.
