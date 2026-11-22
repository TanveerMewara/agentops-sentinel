# Lesson 6: Approval belongs to an exact action

## The problem

A person approves a viewing for 10:00. Before execution, the agent changes the
appointment to 11:00. Should the original approval still allow that booking? No:
it authorized different details. This lesson makes that rule explicit in code.

We are implementing a standalone approval-rule model, not an authenticated approval
API. No appointment is submitted, and there is no database or browser interface.
Lesson 3 database verification remains pending; this does not complete it.

## Run the example

```powershell
.\.venv\Scripts\python.exe lessons/06_action_approvals.py
```

Expected: changed details are blocked, original details pass, and using the same
approval again is blocked. This uses only Python's standard library.

## New concepts

- Proposal: the exact action waiting for a decision.
- Approval: permission for that particular proposal, with an expiry time.
- Rejection: declining a proposal before approving it.
- Revocation: withdrawing an unused approval after it was granted.
- Consumption: marking a grant used to authorize an action locally.
- Timezone-aware time: a date/time carrying its UTC offset. This avoids comparing
  ambiguous local times. The demo uses UTC for approval expiry; booking slots are
  still lesson strings, not a finished timezone-aware calendar implementation.

We use the enums, dataclasses, and immutable snapshots introduced previously.
There is no new third-party package.

## Follow lessons/06_action_approvals.py

1. BookingAction stores operation ID, customer, and slot. Being frozen prevents
   normal reassignment; it does not make the object a security boundary.
2. ApprovalState lists pending, approved, rejected, revoked, and consumed.
3. Approval stores a snapshot of the exact proposed action plus its lifecycle.
4. ApprovalBook stores records in a dictionary indexed by a generated approval ID.
5. propose creates a pending proposal; it does not grant permission.
6. approve accepts only a pending proposal and sets an expiry. A second approval
   cannot silently renew the same record.
7. reject and revoke apply to pending and approved proposals respectively.
8. consume checks the state, expiry, and all action fields before marking it used.
   The datetime argument is explicit so tests can explore expiry without sleeping.
9. Failed validation does not consume the grant. The original approved action can
   still pass if nothing else invalidated its permission.

To edit a proposal, create a new one for the new details and request approval again.
A dataclass equality comparison checks all three action fields in this lesson.
Production snapshots must also bind tenant, actor, tool, destination, schema version,
and every relevant argument. Comparing these three fields is not universal authorization.

## Test it

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_action_approvals.py -v
```

Eight tests cover pending and missing approvals, every action field, exact expiry,
just-before-expiry, rejection, revocation, reuse, immutable snapshots, and invalid
clock/duration inputs. All eight passed in this workspace. They use an explicit
clock, so they run immediately instead of waiting five minutes.

## Important boundary: authorization is not execution

Consuming approval does not mean the booking succeeded. If the worker crashes
immediately after consumption, this dictionary cannot recover the intended work.
Later, approval consumption and creation of a durable authorized operation must
happen in one database transaction. Workers then recover that operation, instead
of pretending each retry needs a brand-new independent approval.

This lesson has no locking: it does not prove safety with simultaneous workers.
Revocation here is checked before consumption. It cannot undo an external action
already performed, and revocation during execution needs a defined policy.

There is no authentication: the script plays both the approver and executor. A real
service must derive the actor and clock on the server, enforce current permissions,
and prevent callers from invoking execution directly. A caller-supplied timestamp
or permission claim must not become trusted input in a production endpoint.

The consume result is deliberately not connected to Lesson 5 yet. We need durable
operation ownership and authenticated authorization before calling it a secure
approval workflow.

## Understanding checkpoint

Explain why the approval ID and operation ID are different. Then explain why
'approval consumed' must not be treated as 'appointment successfully booked.'

Next required work: recover the PostgreSQL environment, verify Lesson 3, and begin
consolidating these lessons into a shared application with a persistent ledger.
