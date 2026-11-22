"""Durable CRM projection and reviewable follow-up drafts."""

from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .provider_registry import CredentialCipher
from .security import Principal, require_roles
from .schemas import FollowupDraftEdit
from .calendar import NativeCalendar, ReserveSlot


def _draft_view(cipher: CredentialCipher, row: dict) -> dict:
    return {
        "draft_id": row["draft_id"], "lead_id": row["lead_id"],
        "run_id": row["run_id"], "channel": row["channel"],
        "status": row["status"],
        "revision": row["revision"],
        "recipient": cipher.decrypt(row["encrypted_recipient"]),
        "subject": cipher.decrypt(row["encrypted_subject"]),
        "body": cipher.decrypt(row["encrypted_body"]),
        "context_snapshot": row["context_snapshot"],
        "approved_at": row["approved_at"], "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def record_viewing_engagement(database, cipher: CredentialCipher,
                              principal: Principal, run_id: str, lead: dict,
                              recommendations: list[dict], result: dict,
                              arguments: dict, *, expected_lead_version: int | None = None) -> dict:
    require_roles("admin", "worker")(principal)
    if not recommendations:
        raise HTTPException(409, "Follow-up requires a selected property.")
    selected = next((item["property"] for item in recommendations
                     if str(item["property"]["property_id"]) == arguments.get("property_id")),
                    recommendations[0]["property"])
    native = "slot_id" in arguments
    native_arguments = ReserveSlot.model_validate(arguments) if native else None
    if native and result.get("status") != "confirmed":
        raise HTTPException(409, "Follow-up requires a confirmed native reservation.")
    booking_id = result.get("reservation_id") if native else result.get("booking_id")
    if not isinstance(booking_id, str) or not booking_id:
        raise HTTPException(409, "Follow-up requires a confirmed booking.")
    slot = (f"{arguments['starts_at']} to {arguments['ends_at']}" if native else arguments.get("slot"))
    if not isinstance(slot, str) or not slot.strip():
        raise HTTPException(409, "Follow-up requires the confirmed viewing slot.")
    subject = "Your viewing appointment is confirmed"
    body = (
        f"Hello {lead['customer']},\n\n"
        f"Your requested viewing appointment at {slot} is confirmed. "
        f"Your booking reference is {booking_id}.\n\n"
        f"Recommended listing: {selected['title']} in {selected['locality']}, "
        f"{selected['city']}. The team will confirm the property to visit.\n\n"
        "Reply to this email if you would like a person from the property team to help."
    )
    if "property_id" in arguments:
        body = body.replace("Recommended listing:", "Confirmed property:").replace(
            " The team will confirm the property to visit.", "")
    context = {
        "lead_version": expected_lead_version or lead["version"],
        "property_id": str(selected["property_id"]),
        "property_version": selected["current_version"],
        "booking_id": booking_id,
        "slot": slot,
    }
    if native:
        context["reservation_id"] = booking_id
    with database.connect() as connection:
        reservation_ready = True
        if native:
            # Same property lock as cancellation: a cancelled booking cannot race
            # engagement creation into producing a live confirmation draft.
            NativeCalendar.property(connection, principal.organization_id, native_arguments.property_id)
            reservation = connection.execute("""SELECT r.*,s.property_id,s.property_version,
                s.starts_at,s.ends_at FROM estate_calendar_reservations r
                JOIN estate_calendar_slots s ON s.slot_id=r.slot_id AND s.organization_id=r.organization_id
                WHERE r.organization_id=%s AND r.reservation_id=%s""",
                (principal.organization_id, booking_id)).fetchone()
            if (reservation is None or str(reservation["run_id"]) != run_id
                    or reservation["slot_id"] != native_arguments.slot_id
                    or reservation["property_id"] != native_arguments.property_id
                    or reservation["property_version"] != native_arguments.property_version
                    or reservation["starts_at"] != native_arguments.starts_at
                    or reservation["ends_at"] != native_arguments.ends_at):
                raise HTTPException(409, "Follow-up reservation evidence does not match this run.")
            reservation_ready = reservation["status"] == "confirmed"
        run = connection.execute(
            "SELECT run_id FROM sentinel_runs WHERE run_id=%s AND organization_id=%s FOR UPDATE",
            (run_id, principal.organization_id),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found.")
        previous = connection.execute(
            """SELECT details FROM estate_engagement_events WHERE run_id=%s
               AND organization_id=%s AND event_type='viewing.engagement_recorded'""",
            (run_id, principal.organization_id),
        ).fetchone()
        if previous:
            return {"crm_contact_id": previous["details"].get("crm_contact_id"),
                    "followup_draft_id": previous["details"].get("followup_draft_id",
                                                               previous["details"].get("draft_id"))}
        current = connection.execute(
            """SELECT current_version, qualification_status, outreach_consent,
                      encrypted_contact_email FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s FOR UPDATE""",
            (lead["lead_id"], principal.organization_id),
        ).fetchone()
        ready = (reservation_ready and current["current_version"] == context["lead_version"]
                 and current["qualification_status"] == "qualified"
                 and current["outreach_consent"] and bool(lead.get("contact_email"))
                 and current["encrypted_contact_email"] is not None
                 and cipher.decrypt(current["encrypted_contact_email"]) == lead["contact_email"])
        contact = connection.execute(
            """INSERT INTO estate_crm_contacts
               (crm_contact_id, lead_id, organization_id, stage, last_run_id,
                booking_id, selected_property_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (lead_id) DO UPDATE SET stage=excluded.stage,
                   last_run_id=excluded.last_run_id, booking_id=excluded.booking_id,
                   selected_property_id=excluded.selected_property_id,
                   updated_at=now() RETURNING *""",
            (uuid4(), lead["lead_id"], principal.organization_id,
             "viewing_booked" if ready else "human_review", run_id,
             booking_id, selected["property_id"]),
        ).fetchone()
        draft = connection.execute(
            """INSERT INTO estate_followup_drafts
               (draft_id, lead_id, run_id, organization_id, channel,
                encrypted_recipient, encrypted_subject, encrypted_body,
                context_snapshot, created_by_key_id)
               VALUES (%s, %s, %s, %s, 'email', %s, %s, %s, %s, %s)
               ON CONFLICT (run_id) DO NOTHING RETURNING *""",
            (uuid4(), lead["lead_id"], run_id, principal.organization_id,
             cipher.encrypt(lead["contact_email"]), cipher.encrypt(subject),
             cipher.encrypt(body), Jsonb(context), principal.api_key_id),
        ).fetchone() if ready else None
        if ready and draft is None:
            draft = connection.execute(
                """SELECT * FROM estate_followup_drafts
                   WHERE run_id=%s AND organization_id=%s""",
                (run_id, principal.organization_id),
            ).fetchone()
        connection.execute(
            """INSERT INTO estate_engagement_events
               (organization_id, lead_id, run_id, event_type, details, actor_key_id)
               VALUES (%s, %s, %s, 'viewing.engagement_recorded', %s, %s)
               ON CONFLICT (run_id, event_type) DO NOTHING""",
            (principal.organization_id, lead["lead_id"], run_id,
             Jsonb({"crm_contact_id": str(contact["crm_contact_id"]),
                    "draft_id": str(draft["draft_id"]) if draft else None,
                    "followup_draft_id": str(draft["draft_id"]) if draft else None,
                    "review_required": not ready, "booking_id": booking_id}),
             principal.api_key_id),
        )
    return {"crm_contact_id": str(contact["crm_contact_id"]),
            "followup_draft_id": str(draft["draft_id"]) if draft else None}


def list_crm_contacts(database, principal: Principal, limit: int) -> list[dict]:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        return connection.execute(
            """SELECT crm_contact_id, lead_id, stage, last_run_id, booking_id,
                      selected_property_id, created_at, updated_at
               FROM estate_crm_contacts WHERE organization_id=%s
               ORDER BY updated_at DESC, crm_contact_id LIMIT %s""",
            (principal.organization_id, limit),
        ).fetchall()


def list_followup_drafts(database, cipher: CredentialCipher, principal: Principal,
                         limit: int, status: str | None) -> list[dict]:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT * FROM estate_followup_drafts
               WHERE organization_id=%s AND (%s::text IS NULL OR status=%s)
               ORDER BY created_at DESC, draft_id LIMIT %s""",
            (principal.organization_id, status, status, limit),
        ).fetchall()
    return [_draft_view(cipher, row) for row in rows]


def approve_followup_draft(database, cipher: CredentialCipher,
                           principal: Principal, draft_id: str, expected_revision: int) -> dict:
    require_roles("admin", "reviewer")(principal)
    with database.connect() as connection:
        binding = connection.execute("""SELECT context_snapshot FROM estate_followup_drafts
            WHERE draft_id=%s AND organization_id=%s""", (draft_id, principal.organization_id)).fetchone()
        if binding is not None and binding["context_snapshot"].get("reservation_id"):
            NativeCalendar.property(connection, principal.organization_id,
                                    binding["context_snapshot"]["property_id"])
        row = connection.execute(
            """SELECT * FROM estate_followup_drafts
               WHERE draft_id=%s AND organization_id=%s FOR UPDATE""",
            (draft_id, principal.organization_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Follow-up draft not found.")
        if row["revision"] != expected_revision:
            raise HTTPException(409, "Draft changed; refresh and review the current revision.")
        if row["context_snapshot"].get("reservation_id"):
            reservation = connection.execute("""SELECT status FROM estate_calendar_reservations
                WHERE organization_id=%s AND reservation_id=%s AND run_id=%s""",
                (principal.organization_id, row["context_snapshot"]["reservation_id"], row["run_id"])).fetchone()
            if reservation is None or reservation["status"] != "confirmed":
                raise HTTPException(409, "Viewing was cancelled; this confirmation cannot be approved.")
        if row["status"] == "approved":
            return _draft_view(cipher, row)
        if row["status"] != "draft":
            raise HTTPException(409, "Follow-up is not an approvable draft.")
        lead = connection.execute(
            """SELECT current_version, qualification_status, outreach_consent, encrypted_contact_email
               FROM estate_leads WHERE lead_id=%s AND organization_id=%s FOR SHARE""",
            (row["lead_id"], principal.organization_id),
        ).fetchone()
        if (lead["current_version"] != row["context_snapshot"]["lead_version"]
                or lead["qualification_status"] != "qualified"
                or not lead["outreach_consent"]
                or lead["encrypted_contact_email"] is None
                or cipher.decrypt(lead["encrypted_contact_email"]) != cipher.decrypt(row["encrypted_recipient"])):
            raise HTTPException(409, "Lead changed; this follow-up needs a new review.")
        row = connection.execute(
            """UPDATE estate_followup_drafts SET status='approved',
                      approved_by_key_id=%s, approved_at=now(), updated_at=now()
               WHERE draft_id=%s RETURNING *""",
            (principal.api_key_id, row["draft_id"]),
        ).fetchone()
        connection.execute(
            """INSERT INTO estate_engagement_events
               (organization_id, lead_id, run_id, event_type, details, actor_key_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (principal.organization_id, row["lead_id"], row["run_id"],
             f"followup.approved.revision_{row['revision']}",
             Jsonb({"draft_id": str(row["draft_id"]), "revision": row["revision"]}), principal.api_key_id),
        )
    return _draft_view(cipher, row)


def edit_followup_draft(database, cipher, principal, draft_id, body: FollowupDraftEdit):
    require_roles("admin", "reviewer")(principal)
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM estate_followup_drafts WHERE draft_id=%s AND organization_id=%s FOR UPDATE",
            (draft_id, principal.organization_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Follow-up draft not found.")
        if row["status"] == "cancelled" or row["revision"] != body.expected_revision:
            raise HTTPException(409, "Draft changed or was cancelled; refresh before editing.")
        row = connection.execute(
            """UPDATE estate_followup_drafts SET encrypted_subject=%s, encrypted_body=%s,
                      revision=revision+1, status='draft', approved_at=NULL,
                      approved_by_key_id=NULL, updated_at=now() WHERE draft_id=%s RETURNING *""",
            (cipher.encrypt(body.subject), cipher.encrypt(body.body), draft_id),
        ).fetchone()
        connection.execute(
            """INSERT INTO estate_engagement_events
               (organization_id, lead_id, run_id, event_type, details, actor_key_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (principal.organization_id, row["lead_id"], row["run_id"],
             f"followup.edited.revision_{row['revision']}",
             Jsonb({"draft_id": str(row["draft_id"]), "revision": row["revision"]}), principal.api_key_id),
        )
    return _draft_view(cipher, row)


def run_engagement_outcomes(database, principal, run_id):
    require_roles("admin", "developer", "reviewer", "worker")(principal)
    with database.connect() as connection:
        run = connection.execute("SELECT status FROM sentinel_runs WHERE run_id=%s AND organization_id=%s",
                                 (run_id, principal.organization_id)).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found.")
        calls = connection.execute(
            "SELECT tool_call_id, status, result FROM sentinel_tool_calls WHERE run_id=%s AND organization_id=%s ORDER BY sequence",
            (run_id, principal.organization_id),
        ).fetchall()
        event = connection.execute(
            """SELECT details FROM estate_engagement_events WHERE run_id=%s AND organization_id=%s
               AND event_type='viewing.engagement_recorded'""", (run_id, principal.organization_id),
        ).fetchone()
        draft = connection.execute(
            "SELECT draft_id, status, revision FROM estate_followup_drafts WHERE run_id=%s AND organization_id=%s",
            (run_id, principal.organization_id),
        ).fetchone()
        reservation = connection.execute("""SELECT reservation_id,slot_id,status
            FROM estate_calendar_reservations WHERE run_id=%s AND organization_id=%s""",
            (run_id, principal.organization_id)).fetchone()
    return {"run_id": run_id, "run_status": run["status"], "tool_actions": calls,
            "crm": {"status": "recorded" if event else "not_recorded",
                    "contact_id": event["details"].get("crm_contact_id") if event else None},
            "followup": dict(draft) if draft else {"status": "blocked" if event else "not_created"},
            "reservation": dict(reservation) if reservation else None,
            "review_required": bool((event and event["details"].get("review_required"))
                                    or (reservation and reservation["status"] == "cancelled")),
            "delivery": {"status": "not_sent", "integration_installed": False}}
