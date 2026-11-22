# Booking provider outage guard

Operations pulse now shows a read-only snapshot of the installed reference guard:
dispatch permitted, dispatch paused, or checking recovery. Paused snapshots include
the cooldown remaining at capture. A zero cooldown still means paused until a
successful probe or validated receipt confirms recovery. Refreshing signals never
contacts the provider, changes the circuit, or dispatches a booking.

The shared-provider signal contains only state, cooldown, and API-process scope.
It excludes failure counts, organization identities, URLs, credentials, and buyer
arguments. Operational counters remain scoped to the authenticated organization;
the guard explicitly describes a shared provider in the current API process.
Deployments without the reference adapter report no guard instead of invented
provider health. Existing API versions without this field also display Not reported.

The reference booking adapter has a process-local circuit breaker. Five temporary
network/HTTP failures without a validated booking receipt pause new booking writes.
Temporary failures include timeouts, network errors, HTTP 408/425/429, and HTTP 5xx.
Missing receipts, redirects, and malformed evidence do not authorize another write.

Execution checks availability before claiming the operation or consuming its
approval. A blocked request returns HTTP 503 with a Retry-After header. The worker's
existing transient-error backoff handles this response. An approval can still
expire while waiting; reopening the circuit does not renew or replace it.

After a 30-second cooldown, one caller may perform GET /health. Only a JSON response
with status equal to "ok" reopens dispatch. Other concurrent callers remain blocked
while that probe runs. A failed probe starts another cooldown. The probe never
replays the uncertain booking POST.

Receipt reconciliation bypasses the write guard and retains its maximum of three
read attempts. A validated matching receipt also closes the circuit. Temporary
failures during recovery count toward the circuit and extend its cooldown.

Execution checks the circuit again immediately before dispatch. If it opened after
the ledger claim, the claimed action retains an uncertain result and uses the
existing evidence-only recovery path. In-flight requests cannot be cancelled by
opening the circuit. A successful health probe is evidence of service availability,
not proof that any uncertain booking succeeded.

The circuit is shared by the reference adapter within one API process, including
its legacy and registered-tool execution paths. It resets on process restart and
is not coordinated across API processes or hosts. It protects the configured
booking endpoint across organizations in that process. This does not implement
provider-wide distributed limits or circuit breakers for arbitrary custom adapters.

Deployments can supply a ProviderCircuit to BookingAdapter to choose validated
failure thresholds and cooldowns. The defaults need real provider/load testing;
this local implementation does not establish production readiness. Providers must
implement the expected read-only health endpoint to reopen dispatch through probes.
