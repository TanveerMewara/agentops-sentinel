# Local pilot threat model and security boundaries

This is a reviewable threat model, not certification. The selected deployment is
one laptop with native PostgreSQL, Python, Node, and service keys; Docker is excluded.

## Assets and trust boundaries

Protect organization data, encrypted lead contacts/provider credentials, approval
authority, frozen run/tool contracts, durable receipts, and execution budgets.
Enquiries, listing descriptions, retrieval content, model outputs, MCP arguments,
HTTP bodies and remote responses are untrusted. Service keys authorize specific
roles; developers do not inherit reviewer/worker authority. Deployment-installed
Python adapters, local configuration, the host, and database administrators are
trusted infrastructure. A compromised host/deployment is outside the current guarantee.

Models propose structured actions. Their prose cannot grant tool permission or
human approval. The run freezes permissions; arguments must satisfy that contract,
and high-risk dispatch requires exact-action, expiring, single-use approval. The
ledger and per-integration evidence determine outcomes. A model's claim of success
is not a receipt. Changed actions need a new approval; uncertainty never authorizes
blind replay. Native calendar writes serialize the property's capacity in PostgreSQL.

## Scripted attack boundaries

- Ungranted tool IDs and fabricated approval/exfiltration fields are rejected by
  the existing permission/contract boundary. This does not detect malicious prose
  that still satisfies a permitted string field.
- Validation diagnostics omit rejected values, enum text, arbitrary extra keys,
  and dynamic nested field names. Tool validation retains a 422 response and a
  root path, rather than echoing inputs through JSON Schema messages.
- Client redirect/TLS tests protect credentials and avoid replaying uncertain writes.
  This is local transport evidence, not a production proxy/network audit.
- Calendar role guards and adapter contract isolation are unit-tested. Real tenant,
  approval, overlap and receipt-recovery checks run separately against PostgreSQL.
- Authenticated stdio MCP declares read-only capabilities. Remote MCP/OAuth and
  testing arbitrary third-party tools remain unfinished.

Run the local security regression lab:

```powershell
.\.venv\Scripts\python.exe scripts\security_lab.py
```

Its ignored `.local/security-lab/latest.json` contains group names, static test IDs,
counts, statuses and explicit coverage gaps. It omits attack values, subtest
parameters, skip reasons, stdout/stderr and tracebacks. Failed, skipped, empty and
errored checks cannot become a passing report. The report is an unsigned local
artifact: someone controlling the filesystem can edit it. It is not approval
evidence, a deployment gate, a security score or a readiness certificate.

## Remaining threats and release work

Representative prompt-injection campaigns using real models, cross-user/session
attacks, malicious retrieval propagation, consent/customer binding, downstream
exfiltration, full prompt/output/checkpoint/log redaction, browser XSS/interaction
testing, production identity, CSRF/session design, OAuth, pre-authentication limits,
organization quotas, load/DoS and infrastructure compromise still require work.
Encrypted contact/provider fields do not imply that every argument, event,
checkpoint or model response is encrypted or comprehensively redacted.

API validation redaction does not prevent malicious content reaching a permitted
downstream destination. Human approval is a control with usability and social
engineering risks, not a universal defense. Independently review each real adapter's
destination restrictions, data scope, failure modes and evidence semantics before
using real customer data. The local pilot and its fictional tests are not an outside
user pilot or production security assessment.
