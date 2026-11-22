"""Explicit native scheduling for automatic EstateFlow; no external provider."""
import json
from fastapi import HTTPException

from .adapters import contract_digest
from .calendar import RESERVE_CONTRACT, ReserveSlot
from .registry import create_agent, create_tool, grant_tool
from .runs import create_agent_version
from .schemas import AgentCreate, ToolCreate, AgentToolGrantCreate, AgentVersionCreate
from .security import require_roles


def is_native_reservation(contract):
    return contract_digest(contract) == contract_digest(RESERVE_CONTRACT)


def configure(database, principal, adapters):
    require_roles("admin", "developer")(principal)
    adapters.resolve(RESERVE_CONTRACT)
    agent, _ = create_agent(database, principal, AgentCreate(
        slug="estateflow_native_viewings", display_name="EstateFlow native viewings",
        description="Lead-bound automatic viewing workflow using offered native calendar slots."))
    tool, _ = create_tool(database, principal, ToolCreate.model_validate(RESERVE_CONTRACT))
    grant_tool(database, principal, str(agent["agent_id"]), str(tool["tool_id"]),
               AgentToolGrantCreate(max_calls_per_run=1))
    version, _ = create_agent_version(database, principal, str(agent["agent_id"]),
        AgentVersionCreate(version="1.0.0", model_alias="deterministic_estateflow", max_steps=1,
            instructions="Reserve only the exact calendar_slot from the frozen property recommendations. "
                         "Require human approval. Do not substitute properties, times or tools."))
    return {"agent_id": str(agent["agent_id"]), "agent_version_id": str(version["agent_version_id"]),
            "tool_id": str(tool["tool_id"])}


def offered_slot(database, principal, slot_id, recommendations):
    with database.connect() as connection:
        slot = connection.execute("""SELECT s.*, (s.active AND s.starts_at>now()
            AND p.listing_status='active' AND p.current_version=s.property_version
            AND NOT EXISTS (SELECT 1 FROM estate_calendar_reservations r
                JOIN estate_calendar_slots booked ON booked.slot_id=r.slot_id
                    AND booked.organization_id=r.organization_id
                WHERE r.organization_id=s.organization_id AND r.status='confirmed'
                    AND booked.property_id=s.property_id
                    AND booked.starts_at<s.ends_at AND booked.ends_at>s.starts_at)) AS available
            FROM estate_calendar_slots s JOIN estate_properties p
                ON p.property_id=s.property_id AND p.organization_id=s.organization_id
            WHERE s.organization_id=%s AND s.slot_id=%s""",
            (principal.organization_id, slot_id)).fetchone()
    if slot is None:
        raise HTTPException(404, "Viewing slot not found.")
    if slot["available"] and not any(str(item["property"]["property_id"]) == str(slot["property_id"])
               and item["property"]["current_version"] == slot["property_version"]
               for item in recommendations):
        raise HTTPException(409, "Viewing slot is outside the frozen property recommendations.")
    arguments = ReserveSlot.model_validate({key: slot[key] for key in
        ("slot_id", "property_id", "property_version", "starts_at", "ends_at")}).model_dump(mode="json")
    return arguments, bool(slot["available"])


def validate_native_decision(decision, tool, arguments):
    # Shape validation alone cannot bind a model to the requested resource.
    if (decision.tool_id != str(tool["tool_id"])
            or json.dumps(decision.arguments, sort_keys=True) != json.dumps(arguments, sort_keys=True)):
        raise HTTPException(422, "Model changed the exact requested calendar action.")
