# Agreed product scope

## User direction

Product clarification: AgentOps Sentinel is the standalone, domain-independent
developer product. EstateFlow AI is an optional example integration used to test
Sentinel, not part of its required product scope or a prerequisite for onboarding.
Other agents connect through supported APIs, clients and execution adapters.
"Any agent" means integration compatibility across domains, not automatic access
to arbitrary agents' internals or correctness without explicit expectations.

Latest delivery direction: finish implementation first and teach the architecture
afterward. Docker is excluded because it is unsupported on the user's laptop.
The first launch is a local laptop pilot; hosting follows separately. The broader
capability list below remains the agreed target, rather than being replaced by
the smaller local pilot milestone.

Build the original ChatGPT proposal for AgentOps Sentinel together with the
additional engineering depth discussed in mentoring. The focused booking and
recovery examples are initial learning milestones; they do not replace the
broader platform. Preserve clear technology and architecture explanations for
the learning phase after implementation, as requested in the latest direction.

## Original platform capabilities to retain

- Agent registration, LangGraph execution, tool registry, structured validation,
  and execution traces covering model calls, tools, retrieval, status, and timing.
- Run-history and execution-timeline interfaces, token accounting, estimated
  costs, latency tracking, and production monitoring.
- Versioned evaluation datasets; rule-based, reference, LLM-judge, human, and
  trajectory evaluation; offline regression testing and online evaluation.
- Prompt and agent version management; model and retrieval comparisons;
  provider abstraction and model routing.
- Failure simulation, bounded retries, fallback handling, circuit breakers,
  checkpoints, recovery, and execution budgets.
- Durable human approval with approve, reject, and edit-and-approve workflows.
- Security testing for prompt injection, data leakage, unauthorized tools,
  cross-user access, unsafe downstream output, and excessive resource use.
- Authentication, multiple organizations with isolated data, role-based
  permissions, PII redaction, and auditable operations.
- A custom MCP server exposing appropriate platform capabilities and controlled
  testing of external MCP tools, with authentication and permission enforcement.
- Background execution, alerting, deployment, CI/CD, evaluation-based release
  gates, architecture and threat-model documentation, and public benchmark results.

Detection scores and attack-test results must have stated limits. Passing a test
suite does not establish universal safety or hallucination detection.

## EstateFlow AI optional example integration

Retain existing example work separately from Sentinel's release requirements:
website and Instagram
enquiries, lead qualification, property recommendations, follow-up generation,
appointment scheduling, CRM updates, and human handoff. Begin with one viewing
workflow, then expand. External integrations depend on available accounts and
service permissions; simulated and sandbox integrations must be clearly labeled.
New EstateFlow-specific features are optional integration work, not blockers for
the standalone Sentinel release. Sentinel must demonstrate multiple domains and
offer a general agent/run/dataset/policy workspace.

## Additional depth that distinguishes our implementation

- Persist operation identity and reconcile external outcomes after lost responses.
- Handle services with idempotency support, reliable operation lookup, or neither;
  explicitly represent uncertainty when automatic recovery is unsafe.
- Test crashes, concurrent retries, duplicate delivery, and partial completion.
- Bind approval to exact action details; handle expiry, revocation, changed
  arguments, concurrent approvals, and attempts to bypass the approval interface.
- Test invariants across generated event sequences, not only scripted demos.
- Compare ordinary retries, framework persistence, and Sentinel safeguards under
  the same workload. Include a simpler non-agent workflow baseline where relevant.
- Use held-out cases, repeated runs, human calibration of model judges, and
  business-state checks. Report completion, safety, human intervention, latency,
  and cost together so refusal cannot masquerade as reliability.
- Measure operational overhead and behavior when Sentinel components fail.
- Validate a second independent agent integration and improve onboarding using
  feedback from outside developers and domain users.
- Document design tradeoffs, known failures, and guarantees per integration.

## Technology and delivery approach

The original stack is a starting proposal: React or Next.js, Python/FastAPI,
LangGraph, PostgreSQL/pgvector, Redis and background workers, Pydantic,
OpenTelemetry, evaluation tooling, MCP, CI, and monitoring tools. Docker is excluded;
the selected laptop uses native PostgreSQL, a Python virtual environment, and Node.
Introduce each when its purpose is concrete; explain choices and avoid redundant
infrastructure. Scope is comprehensive, implementation is incremental.

For each implementation milestone: complete a working piece, verify its behavior,
and record limitations and remaining scope. Detailed teaching and understanding
checks follow implementation rather than blocking the current build.

The ambition is an exceptional portfolio project and a useful developer product.
A 10/10 assessment must be earned through implementation quality, reproducible
evidence, and user value; it is not guaranteed by completing a feature checklist.

## Local database setup decision

Use PostgreSQL directly on Windows for local development, following the user's
acceptance of this alternative to the stalled Docker engine. PostgreSQL verification
remains required; Docker is excluded from development and packaging/deployment.
Native database installation is verified.

## Build-first and Docker-free direction

The user now wants the complete product built before teaching resumes. Continue
implementation and verification without lesson checkpoints. Docker is excluded
from the selected laptop and release workflow: use native PostgreSQL, a Python
virtual environment, the project-local Node runtime, and documented native service
launchers. A hosted release may use managed PostgreSQL and ordinary application
hosting when accounts are available; containers are not a prerequisite.

## Product intent reaffirmed

Build for real adoption by developers and domain users, not solely a portfolio demo.
Use the curriculum as a learning path while requiring integrated release evidence:
repeatable setup, durable execution, authenticated permission boundaries, safe
schema upgrades, backup/restore, observable failures, and independently tested
onboarding. Lesson code remains explicitly labeled until consolidated and hardened.
Do not label the current application production-ready on the strength of isolated tests.
