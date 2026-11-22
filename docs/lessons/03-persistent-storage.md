# Lesson 3: Remembering bookings after a restart

## The problem

Lesson 2 stores bookings in Python memory. Stopping that program erases both the
booking list and the operation-ID dictionary. We now move those records into
PostgreSQL, a separate database server with storage on disk.

Flow: client -> booking API -> PostgreSQL -> booking API -> client.
This is still the fictional external booking service. Sentinel's own execution
ledger comes later; a database here does not solve every external-service failure.

## New concepts

- Database: organized information that another program can save and retrieve.
- PostgreSQL: the database system we will use in the full project.
- Table: a collection of similarly shaped records. Each booking is a row; its
  booking ID, operation ID, customer, and slot are columns.
- SQL: the language we use to ask the database to insert or read records.
- Primary key: the unique identity of a row, here booking_id.
- Unique constraint: a database-enforced rule forbidding repeated non-null
  operation IDs. Unlike a Python dictionary, this rule applies across API processes.
- NULL: a missing database value. PostgreSQL's default UNIQUE behaviour allows
  multiple NULLs, so our deliberately unprotected requests can still create duplicates.
- Transaction: a group of database work that commits on success or rolls back on
  failure. Commit makes it permanent; rollback discards uncommitted changes.
- Psycopg: the driver that lets Python talk to PostgreSQL.
- Docker image: a packaged database program and its runtime dependencies.
- Container: a running instance of that image.
- Docker Compose: reads compose.yaml and starts the declared service.
- Volume: Docker-managed disk storage that outlives the container.

## Start the database

Docker Desktop must be running with its Linux engine ready. From the project root:

```powershell
docker compose up -d --wait --wait-timeout 60
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Compose starts PostgreSQL 17. The -d option runs it in the background; --wait waits
for the health check. Host port 55432 forwards to PostgreSQL's container port 5432.
Only this computer can connect through that mapping. The Compose password is a
public local teaching password, not a production secret. Use only fictional data.
The image tag follows PostgreSQL 17 updates; it is not pinned to an immutable digest.

To use your own lesson database, set SENTINEL_LESSON_DATABASE_URL in the terminal
before starting the API. Do not point this lesson at an unrelated production database.
If Docker returns an engine error, resolve Docker startup before running DB checks.

## Run the persistent API

In terminal A:

```powershell
.\.venv\Scripts\python.exe -m uvicorn lessons.booking_api_persistent:app --host 127.0.0.1 --port 8001
```

In terminal B:

```powershell
.\.venv\Scripts\python.exe lessons/02_http_client.py --base-url http://127.0.0.1:8001
```

We reuse the Lesson 2 client: the HTTP contract has stayed the same even though
storage changed. The different port lets you keep the old lesson running too.
Open http://127.0.0.1:8001/docs to create and list bookings manually.

Stop terminal A with Ctrl+C, restart it, and list bookings again. They should remain.
Stop the database when finished with docker compose stop. This preserves its volume.
Do not delete the volume if you want to keep the lesson records. A volume is not a backup.

## Read the code in order

Open lessons/booking_api_persistent.py.

1. Booking and BookingRequest are imported from Lesson 2 to keep the same data
   contract. Importing that module does not start its HTTP server.
2. DATABASE_URL tells Psycopg how to find the local database. An environment
   variable can override the teaching default.
3. connect opens a connection. dict_row makes query results dictionaries.
4. initialize_database creates lesson_bookings if it does not exist. This is
   lesson setup, not a schema-migration system; later changes need real migrations.
5. lifespan performs setup when the API starts. It creates the table before serving.
6. GET /health now checks the database too. GET /bookings reads rows with SELECT.
7. POST /bookings attempts INSERT with ON CONFLICT (operation_id) DO NOTHING.
8. RETURNING gives us the newly created booking. If another transaction already
   owns the ID, no new row is inserted; a separate SELECT retrieves the existing one.
9. We compare the original customer and slot. Changed details produce HTTP 409.
10. Exiting the connection context successfully commits. Only then do we delay the
    reply, so a client timeout can occur after a durable booking exists.

SQL uses %s placeholders and a separate values tuple. Psycopg transmits values
safely; do not build SQL by pasting customer text into the query string.

Normal def endpoints run in FastAPI's thread pool. That lets this beginner version
use synchronous database calls without blocking the async event loop. We open one
connection per request; connection pooling and bounded capacity come later.

## Why concurrency needs a database rule

Imagine two callers arriving together. Both checking an ordinary list could find
nothing and both create a booking. Here PostgreSQL arbitrates the unique ID.
One INSERT wins; the other waits for the competing transaction and inserts nothing
if that transaction commits. Its subsequent SELECT can see the winner under the
READ COMMITTED isolation level. READ COMMITTED means each statement sees committed
records as of the start of that statement. This lesson has no delete endpoint.

The operation ID and booking live in one row: they are saved together. This is a
small, intentional design. Later Sentinel needs a richer record of attempts and
outcomes for services whose state lives outside Sentinel's database.

## Repeatable verification

With PostgreSQL running, execute:

```powershell
.\.venv\Scripts\python.exe lessons/03_persistence_checks.py
```

The script starts its own API on an available local port and stops only that process.
It runs the earlier HTTP checks, then verifies:

- A booking commits, the reply times out, the API process is killed, and a retry
  after restart returns that same booking ID.
- Eight requests released together produce one booking and return the same ID.
- An exception inside a database transaction rolls back the inserted row.

Successful fictional test records remain for inspection. Every run uses new IDs.
These checks cover an API crash, not a database power failure or backup recovery.
Read the tests after understanding the server; subprocess controls the temporary
server, Barrier releases concurrent requests together, and ThreadPoolExecutor runs
those requests from separate client threads.

## Limits

No authentication, organization scoping, permissions, real appointment availability,
or production migration/backup system yet. There is no universal exactly-once
promise: the database constraint protects this service's retained operation IDs.
The local failure-injection field remains teaching-only. If PostgreSQL becomes
unavailable during commit, the caller can still face an uncertain outcome; this
lesson does not classify every database error or implement Sentinel reconciliation.

Before the next milestone, explain why saving a booking in PostgreSQL is different
from saving Sentinel's note that it asked some other service to create a booking.

Official references:
- https://www.postgresql.org/docs/current/sql-insert.html
- https://www.psycopg.org/psycopg3/docs/basic/transactions.html
- https://docs.docker.com/get-started/docker-concepts/running-containers/persisting-container-data/

## Verification status in this workspace

The project now uses native PostgreSQL 17.11 on Windows for development. The checks
passed for delayed replies, API-process restart, eight concurrent requests, database
transaction rollback, and a PostgreSQL server restart. Docker is no longer required
for this lesson. See `docs/local-postgresql.md` for the repeatable setup.
