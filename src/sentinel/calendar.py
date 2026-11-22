"""Native scheduling resource: durable decisions, no real calendar/email provider."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .adapters import AdapterResult
from .booking_adapter import EvidenceMismatch
from .security import require_roles


class SlotOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_id: UUID
    property_version: int = Field(ge=1, strict=True)
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def duration(self):
        if not timedelta(minutes=5) <= self.ends_at - self.starts_at <= timedelta(hours=4):
            raise ValueError("A viewing must last between five minutes and four hours.")
        return self


class ReserveSlot(SlotOffer):
    slot_id: UUID


class CancelReservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_id: UUID


def contract(name, model, statuses):
    schema = model.model_json_schema()
    # UUID/date-time formats remain checked by the adapter's Pydantic models.
    return {"name": name, "version": "1.0.0", "description": "Approval-controlled native viewing calendar; no external provider.",
        "input_schema": schema, "output_schema": {"type": "object", "properties": {
            "status": {"type": "string", "enum": statuses},
            "reservation_id": {"type": ["string", "null"]}},
            "required": ["status", "reservation_id"], "additionalProperties": False},
        "risk_level": "high", "approval_mode": "always"}


RESERVE_CONTRACT = contract("reserve_viewing_slot", ReserveSlot, ["confirmed", "unavailable"])
CANCEL_CONTRACT = contract("cancel_viewing_reservation", CancelReservation, ["cancelled", "already_cancelled", "not_found"])


class NativeCalendar:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def property(connection, org, property_id):
        # One resource lock serializes overlapping slots, reservations, and cancellations.
        return connection.execute("SELECT * FROM estate_properties WHERE organization_id=%s AND property_id=%s FOR UPDATE",
                                  (org, property_id)).fetchone()

    def offer(self, principal, offer):
        require_roles("admin", "developer")(principal)
        now = datetime.now(timezone.utc)
        if not now < offer.starts_at <= now + timedelta(days=180):
            raise HTTPException(422, "Offer a future viewing within 180 days.")
        with self.database.connect() as connection:
            prop = self.property(connection, principal.organization_id, offer.property_id)
            if prop is None:
                raise HTTPException(404, "Property not found.")
            if prop["listing_status"] != "active" or prop["current_version"] != offer.property_version:
                raise HTTPException(409, "Property is unavailable or its version changed.")
            row = connection.execute("""INSERT INTO estate_calendar_slots
                (slot_id,organization_id,property_id,property_version,starts_at,ends_at,created_by_key_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (organization_id,property_id,property_version,starts_at,ends_at)
                DO UPDATE SET slot_id=estate_calendar_slots.slot_id RETURNING *""",
                (uuid4(), principal.organization_id, offer.property_id, offer.property_version,
                 offer.starts_at, offer.ends_at, principal.api_key_id)).fetchone()
        return row

    def withdraw(self, principal, slot_id):
        require_roles("admin", "developer")(principal)
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM estate_calendar_slots WHERE organization_id=%s AND slot_id=%s",
                                     (principal.organization_id, slot_id)).fetchone()
            if row is None:
                raise HTTPException(404, "Slot not found.")
            self.property(connection, principal.organization_id, row["property_id"])
            row = connection.execute("UPDATE estate_calendar_slots SET active=FALSE WHERE organization_id=%s AND slot_id=%s RETURNING *",
                                     (principal.organization_id, slot_id)).fetchone()
        return row

    def slots(self, principal, limit=50):
        require_roles("admin", "developer", "reviewer")(principal)
        with self.database.connect() as connection:
            return connection.execute("""SELECT s.*,p.title AS property_title,p.city AS property_city,
                (s.active AND p.listing_status='active'
                AND s.property_version=p.current_version AND NOT EXISTS (
                    SELECT 1 FROM estate_calendar_reservations r JOIN estate_calendar_slots booked
                        ON booked.slot_id=r.slot_id AND booked.organization_id=r.organization_id
                    WHERE r.organization_id=s.organization_id AND r.status='confirmed'
                        AND booked.property_id=s.property_id
                        AND booked.starts_at<s.ends_at AND booked.ends_at>s.starts_at)) AS available
                FROM estate_calendar_slots s JOIN estate_properties p
                    ON p.property_id=s.property_id AND p.organization_id=s.organization_id
                WHERE s.organization_id=%s AND s.starts_at>now()
                ORDER BY s.starts_at,s.slot_id LIMIT %s""", (principal.organization_id, limit)).fetchall()

    def reservations(self, principal, limit=50):
        require_roles("admin", "developer", "reviewer")(principal)
        with self.database.connect() as connection:
            return connection.execute("SELECT * FROM estate_calendar_reservations WHERE organization_id=%s ORDER BY created_at DESC,reservation_id LIMIT %s",
                                      (principal.organization_id, limit)).fetchall()

    @staticmethod
    def fingerprint(context):
        return hashlib.sha256(json.dumps(context.arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def receipt(self, connection, context, action):
        row = connection.execute("SELECT * FROM estate_calendar_decisions WHERE organization_id=%s AND tool_call_id=%s",
                                 (context.organization_id, context.tool_call_id)).fetchone()
        if row is None:
            return None
        if (str(row["run_id"]) != context.run_id or row["action"] != action
                or row["arguments_hash"] != self.fingerprint(context)):
            raise EvidenceMismatch("Calendar evidence does not match the approved action.")
        return AdapterResult(str(row["decision_id"]), row["result"])

    def decide(self, context, action):
        payload = (ReserveSlot if action == "reserve" else CancelReservation).model_validate(context.arguments)
        with self.database.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("estate-calendar:" + context.organization_id + ":" + context.tool_call_id,))
            existing = self.receipt(connection, context, action)
            if existing is not None:
                return existing
            # Validate the tenant/run binding even for deployment-level adapter invocation.
            owner = connection.execute("SELECT 1 FROM sentinel_tool_calls WHERE organization_id=%s AND run_id=%s AND tool_call_id=%s",
                (context.organization_id, context.run_id, context.tool_call_id)).fetchone()
            if owner is None:
                raise EvidenceMismatch("Calendar action is outside the authenticated run.")
            result = self.reserve(connection, context, payload) if action == "reserve" else self.cancel(connection, context, payload)
            decision_id = uuid4()
            connection.execute("""INSERT INTO estate_calendar_decisions
                (decision_id,organization_id,tool_call_id,run_id,action,arguments_hash,result)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""", (decision_id, context.organization_id, context.tool_call_id,
                context.run_id, action, self.fingerprint(context), Jsonb(result)))
        return AdapterResult(str(decision_id), result)

    def reserve(self, connection, context, payload):
        prop = self.property(connection, context.organization_id, payload.property_id)
        if not self.lead_ready(connection, context):
            return {"status": "unavailable", "reservation_id": None}
        slot = connection.execute("SELECT * FROM estate_calendar_slots WHERE organization_id=%s AND slot_id=%s FOR UPDATE",
                                  (context.organization_id, payload.slot_id)).fetchone()
        if slot is None or (slot["property_id"], slot["property_version"], slot["starts_at"], slot["ends_at"]) != (
                payload.property_id, payload.property_version, payload.starts_at, payload.ends_at):
            raise EvidenceMismatch("Slot evidence does not match the approved property and times.")
        overlap = connection.execute("""SELECT 1 FROM estate_calendar_reservations r
            JOIN estate_calendar_slots s ON s.slot_id=r.slot_id AND s.organization_id=r.organization_id
            WHERE r.organization_id=%s AND s.property_id=%s AND r.status='confirmed'
                AND s.starts_at<%s AND s.ends_at>%s LIMIT 1""",
            (context.organization_id, payload.property_id, payload.ends_at, payload.starts_at)).fetchone()
        if (prop is None or prop["listing_status"] != "active" or prop["current_version"] != payload.property_version
                or not slot["active"] or slot["starts_at"] <= datetime.now(timezone.utc) or overlap):
            return {"status": "unavailable", "reservation_id": None}
        reservation_id = uuid4()
        connection.execute("""INSERT INTO estate_calendar_reservations(reservation_id,organization_id,slot_id,run_id,status)
            VALUES (%s,%s,%s,%s,'confirmed')""", (reservation_id, context.organization_id, payload.slot_id, context.run_id))
        return {"status": "confirmed", "reservation_id": str(reservation_id)}

    @staticmethod
    def lead_ready(connection, context):
        run = connection.execute("SELECT input_payload FROM sentinel_runs WHERE organization_id=%s AND run_id=%s",
                                 (context.organization_id, context.run_id)).fetchone()
        if run is None:
            return False
        payload = run["input_payload"]
        if "lead_id" not in payload:
            return True  # Explicit manual desk actions have no lead binding.
        version = payload.get("lead_version")
        if type(version) is not int or version < 1:
            return False
        try:
            lead_id = UUID(str(payload["lead_id"]))
        except (ValueError, TypeError, AttributeError):
            return False
        # Caller already holds the property lock. Hold consent/qualification
        # stable through the committed calendar decision, using the same lock
        # order as engagement creation and cancellation-linked draft approval.
        lead = connection.execute("""SELECT current_version,qualification_status,outreach_consent
            FROM estate_leads WHERE organization_id=%s AND lead_id=%s FOR SHARE""",
            (context.organization_id, lead_id)).fetchone()
        return bool(lead and lead["current_version"] == version
                    and lead["qualification_status"] == "qualified" and lead["outreach_consent"])

    def cancel(self, connection, context, payload):
        row = connection.execute("""SELECT r.*,s.property_id FROM estate_calendar_reservations r
            JOIN estate_calendar_slots s ON s.slot_id=r.slot_id AND s.organization_id=r.organization_id
            WHERE r.organization_id=%s AND r.reservation_id=%s""", (context.organization_id, payload.reservation_id)).fetchone()
        if row is None:
            return {"status": "not_found", "reservation_id": None}
        self.property(connection, context.organization_id, row["property_id"])
        row = connection.execute("SELECT * FROM estate_calendar_reservations WHERE organization_id=%s AND reservation_id=%s FOR UPDATE",
                                 (context.organization_id, payload.reservation_id)).fetchone()
        if row["status"] == "cancelled":
            return {"status": "already_cancelled", "reservation_id": str(payload.reservation_id)}
        connection.execute("UPDATE estate_calendar_reservations SET status='cancelled',cancelled_at=now() WHERE organization_id=%s AND reservation_id=%s",
                           (context.organization_id, payload.reservation_id))
        connection.execute("""UPDATE estate_followup_drafts SET status='cancelled',
            approved_at=NULL,approved_by_key_id=NULL,updated_at=now()
            WHERE organization_id=%s AND run_id=%s
                AND context_snapshot->>'reservation_id'=%s AND status IN ('draft','approved')""",
            (context.organization_id, row["run_id"], str(payload.reservation_id)))
        connection.execute("""UPDATE estate_crm_contacts SET stage='human_review',updated_at=now()
            WHERE organization_id=%s AND last_run_id=%s AND booking_id=%s""",
            (context.organization_id, row["run_id"], str(payload.reservation_id)))
        return {"status": "cancelled", "reservation_id": str(payload.reservation_id)}


class CalendarAdapter:
    def __init__(self, calendar, action):
        if action not in ("reserve", "cancel"):
            raise ValueError("Unsupported calendar action.")
        self.calendar, self.action = calendar, action

    def execute(self, context):
        return self.calendar.decide(context, self.action)

    def reconcile(self, context):
        with self.calendar.database.connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            result = self.calendar.receipt(connection, context, self.action)
        if result is None:
            raise EvidenceMismatch("No durable calendar decision is visible; review required.")
        return result
