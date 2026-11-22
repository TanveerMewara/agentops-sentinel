# Website enquiries and automatic viewing workflows

The authenticated website delivery endpoint is `POST /v1/enquiries/website`.
Call it from your website's server using an organization developer/admin key.
Never place that key in a public website's JavaScript. This endpoint is an
integration API; it does not yet include a public enquiry form or a website plugin.

```json
{
  "delivery_key": "website-delivery-0001",
  "source_sequence": 1,
  "lead": {
    "external_key": "website-enquiry-0001",
    "channel": "website",
    "customer_name": "Fictional Buyer",
    "contact_email": "buyer@example.test",
    "city": "Jaipur",
    "max_budget_inr": "15000000.00",
    "timeline": "within_month",
    "outreach_consent": true
  }
}
```

Persist the delivery key and sequence before sending. Retry the identical JSON
with the same key after a timeout: the first delivery returns 201, a replay 200,
and both return the same frozen receipt. Changing the body under an existing key
returns 409. A new update needs a new delivery key and a greater sequence for that
enquiry. Gaps are allowed; older updates are rejected rather than overwriting
newer buyer requirements. Consent must reflect the buyer's actual choice.

Receipt creation, the lead update, and sequence advancement commit together.
Concurrent copies produce one update. Receipts contain IDs and qualification
status; contact details remain encrypted in the lead record.

In the dashboard, choose **Arrange viewing** for a qualified lead, select an
agent/version with a booking grant, and choose a slot. The request creates a
retry-safe queued run. The native worker discovers it, retrieves listings, plans,
and pauses for exact-action reviewer approval. After approval it resumes booking
and creates the internal CRM projection and follow-up draft. Draft approval is a
separate review step; no email is sent. Agents granted the `2.0.0` booking contract
bind the booking to a listing ID/version; the legacy `1.0.0` contract reserves only
an appointment. See [property booking and review](property-booking-review.md).

Waiting approvals are excluded from worker discovery so a full approval queue
cannot hide newly queued or authorized workflows. Completed booking receipts can
be consumed on graph resumption when another worker finished the action first.

Run the native services using `scripts/dev.py`; no Docker is required. Verify the
delivery boundary with:

```powershell
.\.venv\Scripts\python.exe tests\acceptance_enquiries.py
```

Real website deployment, external CRM/email delivery, richer retry scheduling,
and end-to-end outside-user pilots remain release work.
