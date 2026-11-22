"""Tenant-scoped lead intake, transparent qualification, and human routing."""

import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .provider_registry import CredentialCipher
from .schemas import LeadHandoffRequest, LeadReviewResolve, LeadUpsert
from .security import Principal, require_roles


LEAD_FIELDS = (
    "lead_id", "external_key", "channel", "city", "max_budget_inr",
    "min_bedrooms", "timeline", "outreach_consent", "human_help_requested",
    "qualification_status", "qualification_reasons", "current_version",
    "created_at", "updated_at",
)


def qualification(body: LeadUpsert) -> tuple[str, list[str]]:
    """Rules are intentionally inspectable; this is not an AI lead score."""
    if body.human_help_requested:
        return "human_review", ["person_requested"]
    reasons = []
    if not body.outreach_consent:
        reasons.append("outreach_consent_missing")
    if body.contact_email is None:
        reasons.append("contact_email_missing")
    if body.city is None:
        reasons.append("city_missing")
    if body.max_budget_inr is None:
        reasons.append("budget_missing")
    if body.timeline == "unknown":
        reasons.append("timeline_missing")
    if reasons:
        return "needs_information", reasons
    if body.timeline == "later":
        return "nurture", ["timeline_later"]
    return "qualified", ["requirements_complete"]


def _snapshot(body: LeadUpsert) -> dict:
    return body.model_dump(mode="json")


def _requirements(snapshot: dict) -> dict:
    return {key: snapshot[key] for key in (
        "channel", "city", "max_budget_inr", "min_bedrooms", "timeline",
        "outreach_consent", "human_help_requested",
    )}


def _hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _view(cipher: CredentialCipher, row: dict) -> dict:
    result = {field: row[field] for field in LEAD_FIELDS}
    result["customer_name"] = cipher.decrypt(row["encrypted_customer_name"])
    result["contact_email"] = (
        cipher.decrypt(row["encrypted_contact_email"])
        if row["encrypted_contact_email"] is not None else None
    )
    return result


def _version(connection, principal: Principal, row: dict, requirements: dict) -> None:
    connection.execute(
        """INSERT INTO estate_lead_versions
           (lead_version_id, lead_id, organization_id, version, content_hash,
            requirements, qualification_status, qualification_reasons,
            created_by_key_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (uuid4(), row["lead_id"], principal.organization_id,
         row["current_version"], row["content_hash"], Jsonb(requirements),
         row["qualification_status"], Jsonb(row["qualification_reasons"]),
         principal.api_key_id),
    )


def _event(connection, principal: Principal, lead_id, event_type: str,
           details: dict) -> None:
    connection.execute(
        """INSERT INTO estate_lead_events
           (lead_id, organization_id, event_type, details, actor_key_id)
           VALUES (%s, %s, %s, %s, %s)""",
        (lead_id, principal.organization_id, event_type, Jsonb(details),
         principal.api_key_id),
    )


def upsert_lead(database, cipher: CredentialCipher, principal: Principal,
                body: LeadUpsert) -> tuple[dict, str]:
    require_roles("admin", "developer")(principal)
    snapshot = _snapshot(body)
    content_hash = _hash(snapshot)
    status, reasons = qualification(body)
    requirements = _requirements(snapshot)
    with database.connect() as connection:
        row = connection.execute(
            """INSERT INTO estate_leads
               (lead_id, organization_id, external_key, channel,
                encrypted_customer_name, encrypted_contact_email, city,
                max_budget_inr, min_bedrooms, timeline, outreach_consent,
                human_help_requested, qualification_status,
                qualification_reasons, content_hash, created_by_key_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s)
               ON CONFLICT (organization_id, external_key) DO NOTHING
               RETURNING *""",
            (uuid4(), principal.organization_id, body.external_key, body.channel,
             cipher.encrypt(body.customer_name),
             cipher.encrypt(body.contact_email) if body.contact_email else None,
             body.city, body.max_budget_inr, body.min_bedrooms, body.timeline,
             body.outreach_consent, body.human_help_requested, status,
             Jsonb(reasons), content_hash, principal.api_key_id),
        ).fetchone()
        if row is not None:
            outcome = "created"
        else:
            row = connection.execute(
                """SELECT * FROM estate_leads
                   WHERE organization_id=%s AND external_key=%s FOR UPDATE""",
                (principal.organization_id, body.external_key),
            ).fetchone()
            if row["content_hash"] == content_hash:
                return _view(cipher, row), "unchanged"
            if row["qualification_status"] == "human_review" and (
                "manual_handoff" in row["qualification_reasons"]
            ):
                status, reasons = "human_review", ["manual_handoff"]
            row = connection.execute(
                """UPDATE estate_leads SET channel=%s,
                       encrypted_customer_name=%s, encrypted_contact_email=%s,
                       city=%s, max_budget_inr=%s, min_bedrooms=%s,
                       timeline=%s, outreach_consent=%s,
                       human_help_requested=%s, qualification_status=%s,
                       qualification_reasons=%s, content_hash=%s,
                       current_version=current_version+1, updated_at=now()
                   WHERE lead_id=%s AND organization_id=%s RETURNING *""",
                (body.channel, cipher.encrypt(body.customer_name),
                 cipher.encrypt(body.contact_email) if body.contact_email else None,
                 body.city, body.max_budget_inr, body.min_bedrooms,
                 body.timeline, body.outreach_consent, body.human_help_requested,
                 status, Jsonb(reasons), content_hash, row["lead_id"],
                 principal.organization_id),
            ).fetchone()
            outcome = "updated"
        _version(connection, principal, row, requirements)
        _event(connection, principal, row["lead_id"], f"lead.{outcome}", {
            "version": row["current_version"], "qualification_status": status,
            "qualification_reasons": reasons,
        })
    return _view(cipher, row), outcome


def get_lead(database, cipher: CredentialCipher, principal: Principal,
             lead_id: str) -> dict:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s""",
            (lead_id, principal.organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Lead not found.")
    return _view(cipher, row)


def list_leads(database, cipher: CredentialCipher, principal: Principal,
               limit: int, status: str | None) -> list[dict]:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT * FROM estate_leads
               WHERE organization_id=%s AND (%s::text IS NULL OR
                     qualification_status=%s)
               ORDER BY updated_at DESC, lead_id LIMIT %s""",
            (principal.organization_id, status, status, limit),
        ).fetchall()
    return [_view(cipher, row) for row in rows]


def list_lead_events(database, principal: Principal, lead_id: str) -> list[dict]:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM estate_leads WHERE lead_id=%s AND organization_id=%s",
            (lead_id, principal.organization_id),
        ).fetchone()
        if exists is None:
            raise HTTPException(404, "Lead not found.")
        return connection.execute(
            """SELECT event_id, event_type, details, created_at
               FROM estate_lead_events WHERE lead_id=%s AND organization_id=%s
               ORDER BY event_id""",
            (lead_id, principal.organization_id),
        ).fetchall()


def list_lead_versions(database, principal: Principal, lead_id: str) -> list[dict]:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM estate_leads WHERE lead_id=%s AND organization_id=%s",
            (lead_id, principal.organization_id),
        ).fetchone()
        if exists is None:
            raise HTTPException(404, "Lead not found.")
        return connection.execute(
            """SELECT lead_version_id, lead_id, version, content_hash,
                      requirements, qualification_status,
                      qualification_reasons, created_at
               FROM estate_lead_versions WHERE lead_id=%s
                 AND organization_id=%s ORDER BY version DESC""",
            (lead_id, principal.organization_id),
        ).fetchall()


def request_handoff(database, cipher: CredentialCipher, principal: Principal,
                    lead_id: str, body: LeadHandoffRequest) -> dict:
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s FOR UPDATE""",
            (lead_id, principal.organization_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Lead not found.")
        latest = connection.execute(
            """SELECT details FROM estate_lead_events
               WHERE lead_id=%s AND organization_id=%s
                 AND event_type='lead.handoff_requested'
               ORDER BY event_id DESC LIMIT 1""",
            (lead_id, principal.organization_id),
        ).fetchone()
        if row["qualification_status"] == "human_review" and latest and (
            latest["details"]["reason_code"] == body.reason_code
        ):
            return _view(cipher, row)
        row = connection.execute(
            """UPDATE estate_leads SET qualification_status='human_review',
                   qualification_reasons='["manual_handoff"]'::jsonb,
                   current_version=current_version+1, updated_at=now()
               WHERE lead_id=%s AND organization_id=%s RETURNING *""",
            (lead_id, principal.organization_id),
        ).fetchone()
        previous = connection.execute(
            """SELECT requirements FROM estate_lead_versions
               WHERE lead_id=%s AND version=%s""",
            (lead_id, row["current_version"] - 1),
        ).fetchone()
        _version(connection, principal, row, previous["requirements"])
        _event(connection, principal, lead_id, "lead.handoff_requested", {
            "version": row["current_version"], "reason_code": body.reason_code,
        })
    return _view(cipher, row)


def resolve_review(database, cipher: CredentialCipher, principal: Principal,
                   lead_id: str, body: LeadReviewResolve) -> dict:
    require_roles("admin", "reviewer")(principal)
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s FOR UPDATE""",
            (lead_id, principal.organization_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Lead not found.")
        if row["qualification_status"] != "human_review":
            raise HTTPException(409, "Lead is not awaiting human review.")
        current = _view(cipher, row)
        input_body = LeadUpsert.model_validate({
            key: current[key] for key in (
                "external_key", "channel", "customer_name", "contact_email",
                "city", "max_budget_inr", "min_bedrooms", "timeline",
                "outreach_consent",
            )
        })
        snapshot = _snapshot(input_body)
        status, reasons = qualification(input_body)
        row = connection.execute(
            """UPDATE estate_leads SET human_help_requested=false,
                   qualification_status=%s, qualification_reasons=%s,
                   content_hash=%s, current_version=current_version+1,
                   updated_at=now()
               WHERE lead_id=%s AND organization_id=%s RETURNING *""",
            (status, Jsonb(reasons), _hash(snapshot), lead_id,
             principal.organization_id),
        ).fetchone()
        _version(connection, principal, row, _requirements(snapshot))
        _event(connection, principal, lead_id, "lead.review_resolved", {
            "version": row["current_version"],
            "resolution_code": body.resolution_code,
            "qualification_status": status,
        })
    return _view(cipher, row)


def workflow_lead(database, cipher: CredentialCipher, principal: Principal,
                  lead_id: str, *, include_customer: bool = False,
                  include_contact: bool = False) -> dict:
    """Internal read for the worker; name is decrypted only when planning a call."""
    require_roles("admin", "worker")(principal)
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM estate_leads
               WHERE lead_id=%s AND organization_id=%s""",
            (lead_id, principal.organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Lead not found.")
    result = {
        "lead_id": str(row["lead_id"]), "version": row["current_version"],
        "status": row["qualification_status"],
        "outreach_consent": row["outreach_consent"],
        "city": row["city"], "max_budget_inr": row["max_budget_inr"],
        "min_bedrooms": row["min_bedrooms"],
    }
    if include_customer:
        result["customer"] = cipher.decrypt(row["encrypted_customer_name"])
    if include_contact:
        result["contact_email"] = (
            cipher.decrypt(row["encrypted_contact_email"])
            if row["encrypted_contact_email"] is not None else None
        )
    return result
