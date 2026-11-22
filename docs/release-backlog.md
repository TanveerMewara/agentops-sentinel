# Remaining release work

## Updated standalone-product delivery order

The user clarified that Sentinel is the standalone product and EstateFlow is an
optional test integration. This section supersedes the real-estate-dependent
release order below; existing evidence and integration history are retained.

1. Deliver the general agent/version/run/tool workspace and separate example
   screens. Implemented in this update; frontend verification is recorded in
   [project status](project-status.md).
2. Remove remaining EstateFlow coupling from evaluation facts collection, default
   client configuration and built-in workflow routing through explicit integration
   interfaces. Preserve frozen contracts and existing example API compatibility.
   Generic cases now avoid business reads, the client defaults to external-agent
   metadata, and built-in endpoints reject explicit external runs. Configurable
   runner/facts registration and example-free bootstrap remain open.
3. Deliver external-agent trace/output ingestion and supported framework adapters.
   Verify at least two independent domains, including a real external AI agent.
   Immutable ingestion, a synchronous Python recorder, SDK calls and a dashboard
   inspector are implemented. A LangChain Core/LangGraph callback adapter now has
   a real local graph integration test, and bounded OTLP/JSON conversion supports
   framework-neutral traces. An authenticated OTLP/HTTP JSON `/v1/traces` receiver
   now uses immutable pending receipt and explicit sanitized-output finalization.
   The local Stage 2 milestone now includes runnable plain-Python, compiled LangGraph
   and OpenAI Agents SDK agents. The SDK path executes a real `Agent`/`Runner` with a
   deterministic local model, and PostgreSQL acceptance evaluates five trace domains
   together. A live provider call and an outside-developer trial remain external
   validation work. Stage 3 now adds Protobuf/gzip plus metric/log ingestion,
   versioned cost rates, completeness reporting and retention/deletion controls.
4. Extend general evaluators beyond ledger status/budgets. Implemented locally:
   exact JSON/schema v3, trajectory/budget v4, semantic v5, declared held-out and
   category coverage, weighted cases, immutable human calibration, repeated-run
   uncertainty, prompt/model/retrieval variant comparisons, deterministic online
   sampling and release gates. Remaining external evidence: representative live
   data, live judge-provider trials and human calibration by independent reviewers.
5. Finish generic tool/grant/policy/review/model configuration screens, fault and
   security labs, sessions/onboarding, telemetry/costs, deployment-connected gates.
   Implemented locally in Stage 5: the live control center connects generic tool
   contracts/grants, encrypted model providers, alert policies/inbox, team invites,
   deployment authorization and persistent lab campaigns. Browser sessions use
   server-side expiry and CSRF protection. External SSO, alert delivery and real
   deployment-provider execution belong to operational deployment validation.
6. Verify browser behavior, capacity, service packaging, independent installation,
   operational deployment, recovery and outside-user usefulness. Automated local
   work is implemented: bounded PostgreSQL pooling, measured capacity, offline
   install diagnostics, native process-group management, compiled startup, security/
   failure labs and 64-table restore all pass in the full profile. A connected
   browser, outside installer/user and chosen hosted environment remain external
   evidence; see [Stage 6 release](stage-6-release.md).

Detailed boundaries: [standalone platform](standalone-platform.md). Calendar/CRM/
email/Instagram expansion is optional EstateFlow work, not a prerequisite for
Sentinel's standalone release. No measured overall completion percentage exists.

## Historical integrated-pilot plan

Reviewed: 18 September 2026. This checklist retains the agreed scope in
[product scope](product-scope.md). It is a delivery order, not an additional feature
proposal. Items remain open until their pass conditions have evidence. Existing
API, sandbox and manual implementations do not prove their missing integrations.

## Finish the local laptop release first

1. **Connect automatic EstateFlow to the native calendar.** Implementation is now
   present in a separate native agent and verified by the current passing native
   acceptance/full release profile. This integration item is complete locally.
   Original agent configurations still retain the reference booking adapter.
   Select an available property-version-bound slot, propose its exact reservation,
   pause for approval, resume through the native adapter and derive CRM/follow-up
   outcomes from its verified receipt. Preserve lead-change checks and checkpoint
   replay. Specify how confirmed cancellations update linked business records.
   Pass: end-to-end acceptance covers approval/rejection/expiry, competing buyers,
   changed or withdrawn listings, changed leads, restart/lost-reply recovery,
   cancellation and no duplicate reservation or follow-up. Existing agent versions
   must keep their frozen contracts; migration must be explicit.
2. **Verify the complete dashboard in a browser.** Test connection changes and all
   four roles, lead intake, property evidence, viewing launch, exact review,
   reservation/cancellation/recovery, draft revision approval, evaluations and key
   administration. Check keyboard access, small screens, empty/loading/error states
   and disconnection. Pass: recorded interaction results and fixes; HTTP markup and
   a successful build alone do not close this item. Browser automation currently
   has no connected browser.
3. **Refresh the full release evidence.** Completed for the integrated scheduling
   update on 18 September: all 14 full-profile stages, the final 139-test unit rerun,
   58 security checks and 35 failure checks passed. The restore stage covers all
   44 public tables. Repeat the required checks after relevant later changes.
   The older 13-stage report is historical. Stop the owned preview before its ports/build output
   are used by release checks. Pass: current passing reports, no skipped required
   stages, current 44-table restore evidence and documented failures/limitations.
4. **Measure local capacity and supervise native services.** Exercise concurrent
   enquiry delivery, run creation, reviews and execution; record throughput,
   latency distributions, error rates and resource use. Exercise API/worker/service
   restart and interactive shutdown without stopping unrelated services. Define
   measured supported limits and Windows startup/recovery procedures. Pass: a
   reproducible workload/report and tested procedures, without weakening checks.
5. **Validate installation and usability independently.** Have another developer
   install without Docker, integrate the second agent and complete the documented
   fictional workflow; collect property-domain feedback, fix blocking problems and
   prepare the release/demo guide. Pass: independent installation and workflow
   results plus addressed feedback. Running it ourselves does not close this item.

This milestone remains a local release. Bookings in the reference service are
fictional, CRM records are internal and approved follow-up drafts are not emailed.
It does not complete the full product below or enable internet access for friends.

## Complete the broader agreed product

1. **Real calendar, CRM, email and human handoff.** Implement and test supported
   external adapters, slot synchronization, staff/travel capacity, lead/CRM linkage,
   consent-aware delivery and external handoff. Each adapter needs documented
   operation identity, recovery evidence and uncertainty behavior. Pass: real
   sandbox/provider trials including duplicate delivery, partial completion and
   lost responses. Email must use the exact approved draft revision.
2. **Website and Instagram enquiries.** Deploy the enquiry interface and implement
   the agreed Instagram integration with authenticated deliveries, ordering,
   deduplication and permissions. Pass: actual provider deliveries create/update
   only the intended tenant's leads and replays do not repeat business actions.
3. **Live models and retrieval evidence.** Exercise the hosted-model adapter with
   real credentials, validate pgvector on a compatible native/managed PostgreSQL
   deployment, and compare lexical/vector retrieval with real embeddings and
   independently labeled held-out queries. Pass: reproducible quality, citation,
   latency and usage results; the 12-query fictional fixture is not this evidence.
4. **User accounts and onboarding.** Add sessions/SSO, invitations, organization
   creation/onboarding and member roles; add pre-authentication limits and
   organization quotas. Pass: login/logout/session expiry and revocation work;
   browser/session protections and cross-tenant access are tested. Current API keys
   remain service credentials, not a completed user-account system.
5. **Complete product screens and version management.** Finish agent registration,
   explicit prompt versions, model/routing configuration, onboarding, dedicated run
   and review views and supported edit-and-approve proposals. Pass: users can
   configure and operate supported flows through the UI; edits invalidate old
   approval and produce a newly reviewed exact action. Existing panels and draft
   editing do not imply all these flows exist.
6. **Telemetry, costs and alerting.** OTLP/HTTP JSON/Protobuf/gzip receipt for
   traces, metrics and logs is implemented with run correlation, aggregate
   model/tool/retrieval latency, token usage, versioned rates/estimated cost,
   completeness gaps, privacy filtering and retention/deletion controls. Remaining:
   alert delivery, monitoring-failure/overhead measurements, live outside exporters
   and an operational scheduled purge. Pass still requires those external trials.
7. **Full evaluation and release gates.** Extend reference, trajectory and LLM-judge
   evaluators with human calibration, representative held-out data, repeated-run
   uncertainty, prompt/model/retrieval comparisons and online sampling. Connect
   evaluation gates to release decisions. Pass: reproducible calibrated reports
   measuring task completion, safety, human intervention, latency and cost together.
   Saved business-rule, exact-output, schema and deterministic trajectory evaluation
   plus a gate CLI already exist.
8. **Broader reliability evidence.** Add generated event-sequence invariant tests,
   fault coverage beyond the reference provider, general/distributed circuit and
   recovery policies where needed, and measurements when Sentinel components fail.
   Compare ordinary retries, framework checkpoints and Sentinel with the same
   workload, including a simpler non-agent baseline. Pass: reproducible comparison
   and invariant results; refusals must not count as completed tasks.
9. **Real-model security evaluation.** Test direct/indirect injection, leakage,
   cross-user access, unsafe downstream inputs and resource exhaustion with benign
   controls, explicit limits and a security-results UI. Extend trace/log redaction
   tests. Pass: reproducible attack/benign results with disclosed model/configuration
   and measured false positives. Scripted boundary checks are already implemented;
   they do not detect every malicious instruction in valid string arguments.
10. **Remote MCP and external developer compatibility.** Add authenticated remote
    MCP/OAuth, scoped dataset/policy access and controlled external-tool tests;
    validate an external client and hosted TLS/network behavior. Pass: authorization,
    revoked credentials, tenant isolation and contract/evidence failures are tested
    through a real external installation. Read-only stdio MCP and Python client exist.
11. **Operational deployment.** Exercise hosted CI; package native services or use
    managed hosting without Docker. Configure secrets, monitoring, scheduled/offsite
    backups and a production restore rehearsal. Pass: deployment and recovery
    procedures work in the target environment under measured load. Hosting follows
    the selected local-first release; no deployment is assumed or authorized here.
12. **Adoption and published evidence.** Run real workflow trials with outside
    developers/domain users, address feedback and publish a reproducible benchmark,
    supported integration guarantees, limitations and demo. Pass: independent users
    complete useful tasks and material remaining requirements are openly tracked.

## Dependencies and completion accounting

Continue code and local verification without lesson checkpoints. External trials
need provider accounts/credentials and permissions; independent pilots need other
people; hosted operation needs an environment. These are open dependencies, not
completed features or a reason to stop independent implementation.

The current batch implements local item 1. The complete 11-stage native release
profile passed on 21 September 2026; browser verification remains open. Next local
work is items 2 through 5. No scope is
removed to meet a percentage. There is no measured
overall completion percentage: the conversational 75% figure was a rough scope
estimate. Checklist counts are not effort-weighted percentages or a security score.
Completion requires the agreed capabilities and their pass evidence, or an explicit
user-approved scope change.
