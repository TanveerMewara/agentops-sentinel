"""Atomic website delivery deduplication with ordered lead updates."""
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .leads import _hash, upsert_lead
from .schemas import EnquiryDeliveryCreate, LeadRunCreate, RunCreate
from .runs import create_run
from .security import require_roles


class TransactionDatabase:
    """Reuse the caller's transaction without committing a nested service call."""
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def ingest_delivery(database, cipher, principal, body: EnquiryDeliveryCreate):
    require_roles("admin", "developer")(principal)
    payload_hash = _hash(body.model_dump(mode="json"))
    with database.connect() as connection:
        # Serialize the delivery key before the source lock so concurrent reuse
        # against different enquiries cannot mutate either lead.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (f"{principal.organization_id}:{body.delivery_key}",))
        previous = connection.execute(
            """SELECT payload_hash, receipt FROM estate_enquiry_deliveries
               WHERE organization_id=%s AND delivery_key=%s""",
            (principal.organization_id, body.delivery_key),
        ).fetchone()
        if previous:
            if previous["payload_hash"] != payload_hash:
                raise HTTPException(409, "Delivery key already represents another payload.")
            return previous["receipt"], False
        connection.execute(
            """INSERT INTO estate_enquiry_sources (organization_id, external_key)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (principal.organization_id, body.lead.external_key),
        )
        source = connection.execute(
            """SELECT last_sequence FROM estate_enquiry_sources
               WHERE organization_id=%s AND external_key=%s FOR UPDATE""",
            (principal.organization_id, body.lead.external_key),
        ).fetchone()
        if body.source_sequence <= source["last_sequence"]:
            raise HTTPException(409, "Out-of-order enquiry update; use a newer source sequence.")
        lead, outcome = upsert_lead(
            TransactionDatabase(connection), cipher, principal, body.lead
        )
        receipt = {
            "delivery_id": str(uuid4()), "delivery_key": body.delivery_key,
            "source_sequence": body.source_sequence, "lead_id": str(lead["lead_id"]),
            "lead_version": lead["current_version"],
            "qualification_status": lead["qualification_status"], "outcome": outcome,
        }
        connection.execute(
            """INSERT INTO estate_enquiry_deliveries
               (delivery_id, organization_id, delivery_key, external_key,
                source_sequence, payload_hash, lead_id, receipt)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (receipt["delivery_id"], principal.organization_id, body.delivery_key,
             body.lead.external_key, body.source_sequence, payload_hash,
             lead["lead_id"], Jsonb(receipt)),
        )
        connection.execute(
            """UPDATE estate_enquiry_sources SET last_sequence=%s
               WHERE organization_id=%s AND external_key=%s""",
            (body.source_sequence, principal.organization_id, body.lead.external_key),
        )
    return receipt, True


def create_lead_run(database, principal, lead_id: str, body: LeadRunCreate):
    require_roles("admin", "developer")(principal)
    with database.connect() as connection:
        lead = connection.execute(
            """SELECT current_version,qualification_status, outreach_consent FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s FOR UPDATE""",
            (lead_id, principal.organization_id),
        ).fetchone()
        if lead is None:
            raise HTTPException(404, "Lead not found.")
        payload = {"lead_id": lead_id, "workflow": "estateflow"}
        if body.native_slot_id is not None:
            payload["native_slot_id"] = str(body.native_slot_id)
            previous = connection.execute("""SELECT input_payload FROM sentinel_runs
                WHERE organization_id=%s AND idempotency_key=%s""",
                (principal.organization_id, body.idempotency_key)).fetchone()
            if previous is None:
                payload["lead_version"] = lead["current_version"]
            elif "lead_version" in previous["input_payload"]:
                payload["lead_version"] = previous["input_payload"]["lead_version"]
        else:
            payload["slot"] = body.slot
        if body.property_query:
            payload["property_query"] = body.property_query
        run, created = create_run(TransactionDatabase(connection), principal, RunCreate(
            idempotency_key=body.idempotency_key,
            agent_version_id=body.agent_version_id, input=payload,
        ))
        if created and (lead["qualification_status"] != "qualified"
                        or not lead["outreach_consent"]):
            raise HTTPException(409, "Lead is not ready for a viewing workflow.")
        if created:
            permissions = connection.execute(
                """SELECT contract_snapshot FROM sentinel_run_tool_permissions
                   WHERE run_id=%s AND organization_id=%s
                     AND contract_snapshot->>'name' IN ('book_viewing','reserve_viewing_slot')""",
                (run["run_id"], principal.organization_id),
            ).fetchall()
            from .calendar_workflow import is_native_reservation
            supported = any(is_native_reservation(row["contract_snapshot"])
                            if body.native_slot_id is not None
                            else row["contract_snapshot"]["name"] == "book_viewing"
                            for row in permissions)
            if not supported:
                raise HTTPException(409, "Agent needs a matching active viewing tool grant.")
    return run, created
