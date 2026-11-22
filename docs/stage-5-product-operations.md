# Stage 5: product operations

Stage 5 turns the verified agent/evaluation core into an operable local product.
It remains domain-independent: EstateFlow can exercise these controls, but none of
the new tables, APIs, policies or screens depend on real-estate data.

## Browser identity and onboarding

An administrator can configure the organization profile, issue a short-lived
one-time invitation, and list members. Accepting an invitation creates a member
with a salted `scrypt` password digest and an eight-hour server-side session.
Login is limited before authentication by a privacy-preserving digest of the
client address. The browser receives an HTTP-only, SameSite=Strict session cookie
and a separate SameSite=Strict CSRF cookie. Mutating cookie-authenticated requests
must copy that value into `X-CSRF-Token`; service API-key behavior is unchanged.

The dashboard connection dialog supports either a service key or a member login.
The member's hidden actor credential exists only to preserve the existing audit
foreign-key model and cannot authenticate as a service key. It is excluded from
the service-key administration list. Plaintext passwords, sessions and invitation
tokens are never returned by listing endpoints.

## Operational alerts

Each organization has a policy for failed release gates, incomplete telemetry and
failed-run volume. `POST /v1/alerts/evaluate` evaluates current stored evidence and
creates idempotent, privacy-minimal alert records. The inbox exposes type, severity,
bounded counts/gaps, reference IDs and status rather than prompts, tool arguments,
outputs or exception text. Reviewers and administrators can acknowledge alerts.

This local evaluator is explicit and callable from the control center or a native
scheduler. External alert delivery and hosted scheduling remain deployment work.

## Deployment-connected release gates

Administrators register deployment environments. A developer or administrator can
create a deployment record only for a release gate whose immutable report passed.
The version is unique within an environment; replay may return the same record but
cannot silently substitute another artifact digest or gate. Workers/administrators
record the bounded `approved -> deployed|failed -> rolled_back` lifecycle. Sentinel
records authorization evidence; an external deployment system performs the release.

## Failure and security lab campaigns

Developers queue bounded `failure` or `security` campaigns with a named profile.
Workers claim one queued campaign with `FOR UPDATE SKIP LOCKED`, then submit only
counts, duration and pass/fail. Completion is accepted only from the claiming
worker, and the report receives a deterministic digest. Sensitive test payloads
and provider responses are not stored in the campaign record.

## Product control center

The dashboard's **Control center** uses the live API for:

- alert policy, evaluation, inbox and acknowledgement;
- release-gate and deployment evidence;
- failure/security campaign scheduling and results;
- member invitation and member inventory;
- generic tool-contract registration and per-agent grants;
- encrypted OpenAI provider configuration with masked readback.

The existing agent workspace, evaluations, review queue, access administration,
telemetry/cost summary and operations pulse remain separate focused views.

## API client and verification

`SentinelClient` now includes alert policy/inbox, deployment environment and
authorization, and lab campaign helpers. It retains its no-redirect, no-implicit-
retry and status-only error behavior.

The Stage 5 PostgreSQL acceptance test exercises invitation storage, acceptance,
login/logout, CSRF enforcement, role boundaries, hidden actor credentials, alerts,
failed/passed deployment gates and worker campaign ownership:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.\.venv\Scripts\python.exe tests\acceptance_product_operations.py
```

Stage 6 still owns browser interaction/accessibility evidence, load measurements,
independent installation, hosted service packaging and recovery rehearsal.
