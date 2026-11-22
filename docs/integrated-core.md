# Integrated core design

This document describes code that now exists under `src/sentinel`.

## Request lifecycle

1. A developer API key creates a `book_viewing` operation.
2. PostgreSQL enforces uniqueness of `(organization_id, idempotency_key)`.
3. A reviewer approves the canonical hash of its action type and payload.
4. A worker discovers authorized operations through the organization-scoped API.
5. In one transaction, Sentinel locks the operation, checks approval and expiry,
   consumes approval, records `executing`, and grants an execution-attempt lease.
6. The worker calls the booking adapter outside the database transaction.
   A heartbeat renews its fenced lease while the external call remains active.
7. A matching receipt records `succeeded`; an unusable result records `unknown`.
8. The worker scans `unknown` and lease-expired `executing` operations and claims
   a separate reconciliation lease without repeating the external write.
9. Reconciliation reads external state. Matching evidence records success;
   unresolved evidence records `needs_review` without blindly resubmitting.

Every lifecycle change appends an event in the same transaction as the current
state update. Current state answers "where is it now?"; events answer "how did it
get there?"

## Trust boundaries

- Local API keys are stored in the database as HMAC digests; the pepper stays
  outside the database.
- Every operation query includes the authenticated organization ID. Cross-tenant
  object reads return 404 and list queries contain only that tenant's records.
- Developer keys propose work, reviewer keys authorize it, and worker keys execute.
- The external receipt must match operation ID, customer, and slot and contain a
  booking ID before Sentinel records success.

## Concurrency rules

- PostgreSQL uniqueness resolves concurrent operation creation.
- Row locks serialize approval and execution changes for one operation.
- Only `authorized` can become `executing`, so competing workers cannot both claim it.
- The execution attempt ID fences stale workers: a worker may finish only its own attempt.
- Execution and reconciliation heartbeats keep ownership alive during long external calls.
- Reconciliation refuses an executing operation while its lease is active.
- A reconciliation attempt receives its own fenced lease, so competing recovery
  workers cannot both commit evidence for the same operation.

The worker currently discovers work by polling the API. Transient connectivity and
server failures use bounded exponential backoff with jitter; authentication and
permission failures stop immediately. A later queue or database notification can
reduce latency, while PostgreSQL remains the durable source of truth.

## Agent and tool registry

- Agent slugs and tool name/version pairs are unique inside an organization.
- Tool versions hold strict input and output JSON object schemas.
- High-risk tools are rejected unless their policy always requires approval.
- Agent-tool grants set a maximum call count for each future run.
- Composite foreign keys prevent grants between resources from different organizations.
- Registration and grant changes append organization-scoped audit events.

The registry defines trusted contracts and permissions.

## Versioned run engine

- Agent instructions, model alias, and maximum steps are immutable within a version.
- Run creation is idempotent and snapshots the active tool contracts and grant limits.
- Later registry changes affect future runs only.
- A row lock makes each tool-call reservation consume one run step and one tool call
  atomically, including under competing workers.
- Arguments and results must match the frozen Draft 2020-12 JSON Schemas. Invalid
  payloads do not consume budget.
- Call and run changes append organization-scoped events for later inspection.

High-risk calls enter `awaiting_approval`. A reviewer approves a canonical hash of the
run, tool version, and exact arguments; execution consumes that approval once. The
first whitelisted `book_viewing` adapter is connected to the run engine. Its execution
uses a fenced lease and heartbeat, and an interrupted worker recovers through read-only
external evidence instead of repeating the write. Uninstalled tool adapters return a
clear unsupported response and are excluded from worker discovery.

## Durable EstateFlow graph

- A provider-neutral gateway maps an agent version's model alias to a model provider.
- The deterministic local provider produces structured, repeatable booking decisions
  without requiring a paid model account during reliability tests.
- LangGraph plans, reserves the call through Sentinel, and pauses at a dynamic approval
  interrupt. The graph cannot treat its resume input as authorization; the API first
  verifies the organization-scoped Sentinel call is actually authorized.
- LangGraph checkpoints live in PostgreSQL under an organization/run thread ID. A test
  stops the API while approval is pending, starts a fresh process, and resumes the same
  call without repeating the planning or reservation nodes.
- Reviewer rejection resumes down a rejection branch and cancels the run consistently.

## Hosted model gateway

- An organization admin can configure an OpenAI model alias without exposing the API
  key in API responses. Fernet encryption protects the stored credential, while the
  encryption key stays outside PostgreSQL in the service environment.
- The Responses adapter requests strict JSON Schema output, disables SDK retries so
  Sentinel owns retry policy, sets a bounded timeout, and disables provider-side response
  storage for this decision call.
- Every model decision records provider, model, outcome, latency, response ID, and token
  counts without storing prompts or model output in the usage ledger.
- A hosted timeout, malformed response, unauthorized tool selection, or invalid arguments
  routes through the validated deterministic provider and records a `fallback` outcome.

## EstateFlow property retrieval

- Property records are isolated by organization and use a stable external key for
  idempotent ingestion. Changed records append immutable versions; unchanged replays
  do not create duplicate history.
- Batches of up to 100 records commit in one transaction, preventing partial imports.
- PostgreSQL combines weighted full-text rank with title/location trigram similarity,
  then applies exact city, type, bedroom, price, amenity, and active-listing filters.
- Every result includes its source URI, property version, matched terms, matched fields,
  and applied filters. The complete evidence set is stored under a retrieval ID and can
  be read later through an organization-scoped endpoint.
- A run may supply `property_query` and `property_filters` in its input. The graph
  retrieves before model planning, exposes the exact recommendation and citation in
  the workflow response, and stops before tool reservation when no listing matches.
- The first retrieval for a run saves a complete result snapshot. Retries and API
  restarts reuse that snapshot even if a property changes afterward; a reverted
  listing becomes a new immutable version instead of conflicting with an old hash.
- The native PostgreSQL package exposes `pg_trgm` and `unaccent`, but not `pgvector`.
  Lexical runs report `hybrid_lexical_v1`; exact array-cosine vector search is
  available separately after an admin backfill. The pgvector backend remains
  deployment-dependent.
- The dashboard presents the same search with business filters, result cards, and
  version/source citations. Property ingestion accepts only HTTP/HTTPS source links,
  and the dashboard checks the link protocol before opening it.

## Versioned embeddings and vector search

- An organization admin configures `estate_embeddings` through the existing encrypted
  model-provider endpoint with model ID `text-embedding-3-small`. The embedding
  pipeline requests 512 dimensions, a supported option of the [official OpenAI
  Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create).
- Admin backfill embeds only current active property versions. Each row records the
  immutable property-version ID, model alias/ID, dimensions, and a hash of the
  text supplied to the model. Old embeddings remain for audit but cannot represent
  changed listings. Search refuses to proceed when a matching active listing lacks
  a current embedding.
- The native database runs exact cosine search over PostgreSQL `real[]` values,
  capped at 500 filtered candidates. A database with the pgvector extension can
  run `scripts/enable_pgvector.py` to copy those values into `vector(512)` and use
  exact pgvector cosine distance. The current Windows database does not offer
  pgvector, so the pgvector query branch has not been exercised here. An ANN index
  awaits a measured recall/latency tradeoff.
- Searches report `vector_array_exact_v1` or `vector_pgvector_exact_v1` as the
  actual backend. Results include source URI, current property version, embedding
  ID/model/hash, and a retrieval ID. Provider invocations log token count, latency,
  status, and error class without storing listing text or query text there.
- `scripts/benchmark_retrieval.py` seeds eight fictional listings and evaluates
  12 labeled queries with Recall@3, MRR@3, and end-to-end latency. The current
  lexical baseline is Recall@3 = 0.667. Its synthetic labels are a regression
  fixture; outside-user relevance judgments and a real-vector comparison remain.
  The `--vector` option explicitly enables paid embedding calls after an admin
  has configured an embedding credential.

## Known gaps

- Confirmed lead bookings now create internal CRM contacts and encrypted follow-up
  drafts. Reviewer approval checks the lead's version, qualification, and consent;
  it does not send email. External CRM/email adapters and property-bound booking
  contracts are still needed.

- Lead intake and transparent qualification are implemented with an auditable
  review queue. A run may bind to a qualified lead and rechecks its version and
  consent before the booking call. Multi-step CRM/follow-up actions and external
  delivery remain. Lead contact fields are encrypted, while booking arguments
  and checkpoints need a separate PII-redaction design.

- Recovery of partial, long-running multi-step workflows remains.
- A general adapter SDK and more production integrations remain.
- A live provider call still requires an operator-supplied account and sandbox key.
- Credential key rotation operations and external secret-manager integration remain.
- API-key rotation, expiration, rate limiting, and key administration are pending.
- Production migration locking, downgrade policy, backups, and a separate migration
  identity are pending.
- API list pagination has a hard limit but no cursor.
- The booking service is a persistent fictional integration on the same local
  PostgreSQL instance. It is logically external, not an independent deployment.
- The first operations dashboard is implemented; production session authentication,
  monitoring, trace redaction, evaluations, and threat testing remain.

These gaps prevent a public production-readiness claim today.
