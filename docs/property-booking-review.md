# Property booking and follow-up review

The new `book_viewing` contract version `2.0.0` requires `customer`, `slot`,
`property_id`, and integer `property_version`. Its output remains `booking_id`.
Register this contract and grant it to an agent before creating a run: permissions
are frozen at run creation. The existing version `1.0.0` remains an appointment-only
contract for legacy examples. Contract registration/grant examples are exercised
in `tests/integration_api.py`.

The local planner prefers the property-bound contract. It takes the ID and version
from retrieval evidence. Workflow validation rejects a changed viewing time or a
property outside the frozen recommendations. The exact arguments are included in
the approval hash. Execution checks tenant ownership, active listing status, and
current version. A changed listing requires a new action and review.

The fictional persistent booking service stores the property ID/version with its
operation receipt. The adapter checks those values on execution and read-only
reconciliation; evidence for another listing or version is rejected. This proves
property binding in the local reference integration. A real scheduling provider,
calendar availability, slot conflicts, cancellations, and property-team integration
remain required for production scheduling. The local availability check occurs at
claim time; it cannot guarantee a listing stays available during an external call.

If a separate worker finishes booking before graph resumption, the graph uses the
saved receipt. If the lead subsequently changes, booking stays completed and the
internal CRM records a human-review stage. The workflow does not create an outreach
draft for that changed lead. Replaying engagement cannot overwrite newer CRM state.

Reviewers/admins can edit drafts with:

```text
PATCH /v1/followups/{draft_id}
{ "expected_revision": 1, "subject": "...", "body": "..." }
```

Each save increments the revision, clears approval, and returns the draft to review.
Concurrent/stale saves return 409. Recipient and booking context cannot be edited.
The subject/body remain encrypted; audit events contain IDs and revision numbers.

Approval now requires the revision that was reviewed:

```text
POST /v1/followups/{draft_id}/approve
{ "expected_revision": 2 }
```

The API rejects a stale revision and rechecks lead version, qualification, consent,
and email recipient before approving. This is a deliberate request-contract change
from the earlier empty approval body. The dashboard supplies the current revision.
Approved drafts are still not sent; no external email adapter is installed.

`GET /v1/runs/{run_id}/engagement` returns separate tool-action statuses, CRM
recording, draft revision/status, review requirement, and explicit delivery status.
It contains no decrypted customer contact fields and is scoped to the caller's
organization. A succeeded booking/workflow never implies that an email was sent.

Development, tests, and packaging continue without Docker.
