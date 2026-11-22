# Native viewing calendar

This calendar runs in the project's PostgreSQL database without Docker or an
external provider account. It adds offered appointment slots, availability,
approval-controlled reservations and cancellations, and durable outcome receipts.
It is separate from the older fictional booking bridge. EstateFlow's existing
qualification workflow is not automatically switched to these new tools.

Administrators and developers offer a slot using POST /v1/calendar/slots with
property_id, property_version, starts_at, and ends_at. Times must include a timezone;
the service normalizes them to UTC. A slot must start within the next 180 days and
last between five minutes and four hours. The property must be active at the
offered version. Repeating the exact offer returns the same slot, preserving its
withdrawn state if an operator already withdrew it.

Administrators, developers, and reviewers can read GET /v1/calendar/slots and
GET /v1/calendar/reservations. Both support limit from 1 to 100. Slot availability
is a snapshot, not a hold or a promise. Only reservation commit secures a slot.
Availability requires an active offer, an active unchanged property, and no
overlapping confirmed reservation for that property in the organization.

The default application installs two high-risk, mandatory-approval tool contracts:

- reserve_viewing_slot version 1.0.0: slot_id, property_id, property_version,
  starts_at, and ends_at. These details must match the offered slot.
- cancel_viewing_reservation version 1.0.0: reservation_id.

Register the exact contracts from sentinel.calendar, grant them to an agent, and
create a version/run using the existing registry APIs. Reserve a tool call,
have a reviewer approve the exact action, then execute with worker access. The
calendar has no direct HTTP endpoint that bypasses approval to reserve or cancel.
Custom deployments supplying their own AdapterRegistry must explicitly install
the calendar adapters if they want these tools.

Each tool returns a business status and reservation_id. A completed tool call can
have an unavailable or not_found business outcome; callers must inspect result.status.
Reservation returns confirmed or unavailable. Cancellation returns cancelled,
already_cancelled, or not_found. These decisions are stored atomically with the
reservation change. Unexpected errors remain uncertain under the existing ledger.

The adapter uses the tool-call identity, tenant, run, action, and approved argument
fingerprint to recover its immutable decision. Lost replies are reconciled only
by reading that decision. Repeating a decision never performs another reservation.
An unavailable decision remains unavailable even if the slot later becomes free:
use a fresh tool call and approval to book again. Historical confirmation receipts
remain confirmation evidence for the original action after a separately approved
cancellation; GET /v1/calendar/reservations reports current reservation state.

PostgreSQL serializes changes through the property row, preventing overlapping
reservations even when different offered slots overlap. Adjacent intervals are
allowed. This protects writes using this adapter across API processes connected
to the same database. It is not a constraint against arbitrary direct SQL writes.
Property changes are rechecked under the same resource lock at reservation time.

POST /v1/calendar/slots/{slot_id}/withdraw requires administrator/developer access.
Withdrawal stops future reservation of that offer; it does not silently cancel an
existing reservation. A cancellation requires its own approved tool action.

Run the native acceptance check:

```powershell
.\.venv\Scripts\python.exe tests\acceptance_calendar.py
```

The native/full release-check profiles include this check. The full profile now
contains 14 stages; earlier 13-stage reports remain historical evidence.

This resource models a property's viewing capacity, not agent staffing or travel
time across different properties. It does not send invitations, synchronize with
Google/Microsoft, model recurring hours, or provide external CRM integration.
Local lead/CRM linkage is supported by the automatic native workflow below.
The dashboard's Viewing calendar panel lists the next 100 future
offers and latest 100 reservation records. Administrators/developers can offer
and withdraw times; reviewers can read these records. Counts describe these loaded
records, not the whole database. Browser-local dates are converted to UTC on offer
submission. A withdrawn offer is not automatically reopened by submitting it again.

The panel now proposes reservations/cancellations and exposes their separate review,
execution, receipt recovery, and run closure through the existing versioned-tool
API and exact-action approval lifecycle. Historical
reservation times outside the loaded future offers show their slot identity rather
than an invented date. External scheduling capabilities and real-provider trials
remain required for the broader product.

## Dashboard workflow

1. Connect with a developer/admin key and select **Enable calendar actions**.
   This idempotently registers a manual, single-step desk and its two native tools.
   It creates no booking and calls no model.
2. Offer a future time, then select **Request reservation**. The proposal includes
   the exact property version, slot identity, and UTC interval.
3. Connect with a reviewer/admin key, inspect **Exact action arguments**, then
   approve or reject. Approval lasts five minutes; it can be revoked before use.
4. Connect with a worker/admin key and select **Execute approved action**.
   Inspect **Business outcome**: completed does not necessarily mean confirmed.
5. A developer/admin can **Request cancellation** from a confirmed reservation.
   Cancellation requires its own review and execution.
6. **Close run** closes a completed manual desk run, or cancels a failed/rejected
   one. Unresolved actions and unrelated/multi-step workflows cannot be closed here.

Workers see the action queue but cannot read the slot/reservation listing, configure
the desk, propose, offer, or approve. Reviewers can read calendar records and review
actions. These permissions are enforced by the API. Generic tool reservation
remains restricted to administrator/worker access.

New routes: POST /v1/calendar/configuration, POST /v1/calendar/proposals,
GET /v1/calendar/actions?limit=100, POST /v1/calendar/actions/{tool_call_id}/close.
Proposal identities contain 8–180 letters, digits, underscores, or hyphens. Replay
requires the same original action/arguments; changed requests return conflict.
Run and call creation are separate durable steps with the same replay identity.

The browser retains its current proposal identity in memory on an unconfirmed
response. Reloading loses that memory: inspect the queue before proposing again.
Execution is never automatically retried. **Recover from receipt** waits for an
execution lease to expire and only reads the original decision. Missing or
contradictory evidence requires investigation. Refresh reads state without dispatch.
The queue prioritizes unresolved actions and is capped at 100; it does not claim
to display every action in a large organization.

Existing EstateFlow agent configurations retain the fictional booking bridge;
the manual desk does not migrate them. A separate automatic native configuration
links qualified leads to local reservations and CRM/follow-up records. Preview mode
pauses automatic dispatch. In normal pilot mode, a worker may execute authorized
actions between refreshes. External calendar synchronization, invitations, and
staffing/travel capacity remain unfinished.

## Automatic lead-bound native workflow

1. Offer a future property-version-bound time in **Viewing calendar** with developer
   or administrator access. A time offer creates no reservation.
2. In **Leads**, select **Arrange viewing**, keep **Native viewing calendar**, choose
   an offered slot and select **Enable native viewing agent**. The idempotent
   configuration route creates/reuses the dedicated `estateflow_native_viewings`
   agent/version and exact installed reservation contract. It makes no model call
   and does not migrate an existing agent or run.
3. Create the viewing run. The lead-run route freezes the lead's current version
   under its row lock. In a normal pilot the worker plans automatically; in preview
   mode use the existing Runs workflow controls with worker/admin access.
4. Retrieval uses the selected property's title by default and applies the verified
   buyer's city, budget and bedroom requirements. A supplied property query still
   must return the offered property/version in the frozen recommendations. Planning
   exposes only the exact native reservation tool and binds its arguments to the
   selected slot ID, property ID/version and UTC interval. No substitute time,
   property or legacy booking tool is accepted.
5. Review/approve the exact action with reviewer/admin access. Execute/resume with
   worker/admin access. The adapter checks the immutable run's lead version,
   qualification and consent under the same transaction as the reservation. Direct
   tool execution enforces this boundary too. Lost replies are recovered by receipt
   reads rather than another write.
6. A confirmed receipt links the reservation reference to the internal CRM contact
   and encrypted follow-up draft. A completed tool returning `unavailable` cancels
   the business run with workflow status `slot_unavailable`; it creates no CRM
   booking confirmation or draft. A slot already unavailable during planning creates
   no tool call or approval request.
7. Request/review/execute cancellation in **Viewing calendar**. The same transaction
   cancels linked unsent drafts, clears their current approval and moves the matching
   CRM projection to human review. A newer CRM booking is not overwritten. If
   cancellation occurs before engagement creation, engagement records human review
   without creating a confirmation draft.

New route: `POST /v1/calendar/workflow/configuration` (developer/admin).
`POST /v1/leads/{lead_id}/runs` accepts either `native_slot_id` or the original
free-text `slot`, never both. Both paths require a matching frozen tool permission.
Replay of the same native lead-run request retains the original lead version and
run identity even after a lead changes; this does not authorize a fresh write.
Changed request details still return conflict. Raw native runs with a lead binding
must include an integer `lead_version`; missing/invalid bindings cannot reserve.

The viewing launcher retains its current request identity after an unconfirmed
response. Changing its scheduling inputs starts a new intent. Reloading/closing
loses the identity: inspect Runs before making another request. Connection changes
remount its private session so prior leads, slot choices and notices are cleared.

Historical confirmed receipts remain immutable after cancellation. Current
reservation/draft status is available from the calendar listings and
`GET /v1/runs/{run_id}/engagement`, which includes the reservation and current
review requirement. Workflow completion describes historical execution; it is
not proof that a reservation remains active. The native agent uses the deterministic
local provider by default. No real calendar invitation, external CRM update or
email delivery is performed.
