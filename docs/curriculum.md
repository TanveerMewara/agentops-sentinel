# Project curriculum: 30 planned lessons

This plan covers the original AgentOps Sentinel + EstateFlow proposal and the
additional reliability work in product-scope.md. Thirty is a planning count, not
an estimate derived from feature count or a promise of thirty short chat turns.
Later lessons are larger milestones and may need several coding/explanation sessions.
Bug fixes, outside feedback, account setup, and operational testing can add sessions.
We complete the project by meeting acceptance criteria, not reaching a lesson number.

## Foundations: lessons 1-6

1. Lost responses and duplicate actions. Python experiment and operation identity.
2. HTTP booking API. FastAPI, Pydantic, Uvicorn, JSON, and client timeouts.
3. Persistent bookings. Native PostgreSQL, SQL, transactions, concurrent requests,
   and restart verification. **Implemented and verified with native PostgreSQL;
   Docker is excluded from the selected development and deployment plan.**
4. Operation states. Model unknown outcomes without confusing them with failure.
5. HTTP reconciliation. Adapter receipts, exact evidence checks, read-only lookup.
6. Exact-action approvals. Expiry, rejection, revocation, and local consumption.

Lessons 1, 2, 4, 5, and 6 have scoped checks passing. They are teaching components,
not a completed integrated platform or a percentage measure of product completion.

## Build the durable application: lessons 7-12

7. Resolve the database blocker and verify Lesson 3; consolidate teaching code into
   shared application modules, configuration, schema migrations, and operation ledger.
   **Core implemented and integration-verified with native PostgreSQL.**
8. Background execution. Queue semantics, operation ownership, concurrent workers,
   attempts, checkpoints, restart recovery, and partial workflow failure handling.
   **API-driven polling, fenced and renewed execution/reconciliation leases, automatic
   read-only recovery, and bounded transient-failure backoff are implemented. Queue
   notifications and partial multi-step workflow handling remain.**
9. Identity and permissions. Authentication, organizations, tenant isolation,
   role-based tool access, and cross-tenant database/API tests.
   **API-key authentication, organizations, roles, and cross-tenant API tests are
   implemented. Service-key issuance/expiry/revocation, access audit, identity, and
    admin UI and shared per-key request limits are implemented. Production user
    sessions, pre-authentication proxy limits, and tenant onboarding remain.**
10. Durable approval workflow. Authenticated approve/reject/edit, expiry, revocation,
    atomic authorization plus operation creation, audit records, and bypass tests.
11. External-service capabilities. Idempotent replay, lookup-only services, ambiguous
    services, manual reconciliation, and documented guarantees per adapter.
12. Agent and tool registration. Validated tool schemas, LangGraph integration,
    provider-independent model access, execution limits, and versioned runs.
    **Organization-scoped agent registration, immutable agent/tool versions, strict
    JSON contracts, risk policy, tool grants, versioned run snapshots, atomic budgets,
    exact high-risk call approval, a whitelisted booking dispatcher, and crash-safe
    reconciliation are implemented. A provider-neutral model contract and the first
    PostgreSQL-checkpointed LangGraph approval workflow are also implemented. Hosted
    OpenAI Responses adapter, encrypted credential storage, strict output validation,
    deterministic fallback, and token/latency accounting are implemented. Live sandbox
    validation remains. A general deployment-installed adapter interface, exact
    contract dispatch, and durable local support-ticket adapter are implemented;
    real external provider integrations remain.**

Lesson 7 is a dependency gate: no claims of durable execution or secure integrated
approvals until the database and integration checks pass. Do not keep adding isolated
lessons to avoid resolving the environment.

## EstateFlow and the product interface: lessons 13-18

13. Property retrieval. PostgreSQL/pgvector, data ingestion, evidence-backed property
    recommendations, and a simpler deterministic/single-model baseline.
    **Organization-scoped property storage, atomic/idempotent ingestion, immutable
    versions, structured filters, full-text/trigram ranking, source evidence,
    retrieval audit records, versioned embedding storage, exact array-cosine
    ranking, and a synthetic comparison runner are implemented. Live pgvector
    verification and real-model quality comparison remain.**
14. EstateFlow workflow. Lead qualification, appointment scheduling, CRM updates,
    follow-up drafts, human handoff, and checkpoints in one complete workflow.
    **Lead intake, explicit qualification, a versioned human-review queue, and
    lead-bound booking are implemented. Retrieval freezes results per run and exits
    when no property matches. Confirmed lead bookings create an internal CRM
    projection and encrypted follow-up drafts with reviewer approval. Property-bound
    booking evidence, unavailable-listing rejection, post-booking lead-change
    review, and draft editing with revision-specific approval are implemented.
    External CRM/email delivery and real calendar scheduling remain.**
15. Enquiry integrations. Website and Instagram inputs, delivery deduplication,
    credentials, consent/permissions where needed, and real sandbox contracts.
    **Authenticated website deliveries, retry deduplication, monotonic source
    updates, and dashboard-to-worker viewing launch are implemented. Real website
    deployment, additional supported channels, and outside pilots remain.**
16. React interface foundations. Navigation, agent registration, run history,
   authentication UI, customer enquiry flow, and backend integration.
   **Responsive navigation, live API connection, operation history, recovery
   controls, evidence-backed property search, and a live lead queue/intake form are
   implemented. Agent registration and session auth remain.**
17. Run inspection. OpenTelemetry traces, graph/tool timelines, retrieval context,
    latency, token usage, estimated cost, and redaction before trace storage.
    **Redacted ledger-based run/model/retrieval/engagement timelines and recorded
    token/timing metrics are implemented. OpenTelemetry export and priced costs remain.**
18. Approval and operations UI. Exact action review, rejection/editing, unresolved
   operation inbox, accessible error states, and recovery evidence.
   **Operation inspection, approval/rejection, execution/revocation, unresolved-state
   filtering, and recovery timelines are implemented. Editing and dedicated pages remain.**

External account access may require user setup. A mock connector is labeled as a
mock and does not count as completing a promised live integration.

## Evaluation and measurable reliability: lessons 19-24

19. Evaluation datasets. Versioning, references, representative cases, held-out data,
    business-state assertions, task/tool/argument/groundedness metrics.
    **Immutable tenant-scoped dataset versions, declared category coverage,
    development/validation/test splits, weights and bounded semantic references are
    implemented. Independent proof of real-traffic representativeness remains.**
20. Evaluation engine. Rule/reference evaluators, LLM-as-judge, human scoring and
    calibration, trajectory evaluation, and repeatable offline experiments.
    **Saved-run rules, exact output/schema, trajectory and semantic evaluator v5 are
    implemented with frozen reports, strict provider output, human calibration,
    replay and gate CLIs. Live judge trials and independent human labels remain.**
21. Version comparisons. Prompt/model/retrieval versions, repeated runs, uncertainty,
    regressions by category, cost/quality tradeoffs, and comparison UI.
    **Same-dataset comparisons, prompt/model/retrieval variants, repeated-run
    uncertainty, category deltas and immutable release decisions are implemented.
    Broader live quality/cost trials remain.**
22. Failure lab. Timeouts, rate limits, invalid output, unavailable tools, duplicate
    delivery, worker crashes, partial completion, and generated event-sequence tests.
23. Recovery policies. Bounded backoff, circuit breakers, fallbacks, caching, budgets,
    model routing, and comparisons with ordinary retries and framework persistence.
24. Online evaluation and operations. Sampled production scoring, alerts, service
    health, monitoring, retention, and observability failure/overhead measurements.
    **Deterministic per-tenant sampling with daily limits, one-run replay safety and
    policy-selected immutable experiments is implemented. Alert delivery and
    monitoring failure/overhead measurements remain.**

## Security, developer adoption, and release: lessons 25-30

25. Security evaluation. Threat model, direct/indirect injection, unauthorized tools,
    data leakage, dangerous downstream input, cross-user memory, and false positives.
26. MCP integration. Authenticated platform MCP server, scoped access to traces,
    datasets and policies, and controlled external-tool contract/security testing.
    **Read-only stdio MCP with API authentication, run summaries, and redacted
    timelines is implemented. Remote OAuth, datasets/policies, external-client
    verification, and contract/security testing remain.**
27. Developer integration experience. Documented adapter/client interface, second
    independent agent, quickstart examples, and installation by another developer.
    **Python client and a separate deterministic support-triage example are
    documented and verified locally, including real-loopback HTTP/TLS checks.
    General adapter interfaces and the durable local support-ticket example are
    implemented. External adapters, hosted-network checks, and installation by
    another developer remain.**
28. Deployment and engineering checks. Native service deployment, CI tests,
    eval release gates, secrets, migrations, health checks, backup/restore rehearsal,
    operational runbooks, and appropriate load/capacity tests.
29. Pilot use. Outside developer and property-domain feedback, real workflow trials,
    onboarding friction, bug fixes, and prioritized improvements.
30. Release evidence. Reproducible public benchmark, supported integrations and
    guarantees, known limitations, architecture/threat documentation, demo, and
    final acceptance review with unresolved requirements tracked explicitly.

## What 'complete' means

- The agreed scope has working, tested implementations or explicit user-approved
  scope changes; unavailable integrations do not silently become completed features.
- A developer other than us can install it and integrate the documented second agent.
- The deployed workflow demonstrates approvals, tracing, evaluation, and recovery.
- Benchmark results are reproducible and distinguish simulation from real usage.
- Permission boundaries and uncertain outcomes are tested and documented.
- Deployment, backup/restore, and operational behaviour have been exercised.
- Pilot feedback has been addressed; material limitations remain visible.

No project is permanently finished: this defines a credible first full release.
It does not guarantee a hiring outcome or a 10/10 rating from every interviewer.

Setup update: Lesson 7 uses native PostgreSQL 17.11 on Windows. Persistence,
concurrent creation, rollback, API restart, and database restart checks passed.
Docker is excluded. Packaging will use native services or managed hosting.

