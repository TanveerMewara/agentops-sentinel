"""Purpose-limited manual proposals; booking still uses the approved tool ledger."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .adapters import contract_digest
from .calendar import RESERVE_CONTRACT, CANCEL_CONTRACT, ReserveSlot, CancelReservation
from .registry import create_agent, create_tool, grant_tool
from .runs import create_agent_version, create_run, reserve_tool_call, tool_call_view, finish_run, cancel_run
from .schemas import AgentCreate, ToolCreate, AgentToolGrantCreate, AgentVersionCreate, RunCreate, ToolCallReserve
from .security import require_roles

SLUG = "estateflow_calendar_desk"
CONTRACTS = {"reserve": RESERVE_CONTRACT, "cancel": CANCEL_CONTRACT}


class CalendarProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=180, pattern=r"^[A-Za-z0-9_-]+$")
    action: Literal["reserve", "cancel"]
    arguments: dict

    @model_validator(mode="after")
    def validate_arguments(self):
        (ReserveSlot if self.action == "reserve" else CancelReservation).model_validate(self.arguments)
        return self


def configuration(database, principal, adapters):
    if not all(adapters.supports(contract) for contract in CONTRACTS.values()):
        return None
    with database.connect() as connection:
        version = connection.execute("""SELECT v.agent_version_id,a.agent_id
            FROM sentinel_agents a JOIN sentinel_agent_versions v ON v.agent_id=a.agent_id
            AND v.organization_id=a.organization_id
            WHERE a.organization_id=%s AND a.slug=%s AND a.status='active' AND v.version='1.0.0' AND v.max_steps=1""",
            (principal.organization_id, SLUG)).fetchone()
        if version is None:
            return None
        rows = connection.execute("""SELECT t.* FROM sentinel_tools t JOIN sentinel_agent_tools g
            ON g.tool_id=t.tool_id AND g.organization_id=t.organization_id
            WHERE t.organization_id=%s AND g.agent_id=%s AND t.status='active'
            AND t.name IN ('reserve_viewing_slot','cancel_viewing_reservation') AND t.version='1.0.0'""",
            (principal.organization_id, version["agent_id"])).fetchall()
    tools = {}
    for action, contract in CONTRACTS.items():
        match = next((row for row in rows if contract_digest(row) == contract_digest(contract)), None)
        if match is None:
            return None
        tools[action] = str(match["tool_id"])
    return {"agent_version_id": str(version["agent_version_id"]), "tools": tools}


def configure(database, principal, adapters):
    require_roles("admin", "developer")(principal)
    for contract in CONTRACTS.values():
        adapters.resolve(contract)  # Fail before registry writes if deployment lacks either adapter.
    agent, _ = create_agent(database, principal, AgentCreate(slug=SLUG,
        display_name="Viewing calendar desk", description="Manual native calendar proposals with exact-action approval."))
    for contract in CONTRACTS.values():
        tool, _ = create_tool(database, principal, ToolCreate.model_validate(contract))
        grant_tool(database, principal, str(agent["agent_id"]), str(tool["tool_id"]), AgentToolGrantCreate(max_calls_per_run=1))
    create_agent_version(database, principal, str(agent["agent_id"]), AgentVersionCreate(version="1.0.0",
        instructions="Manual viewing calendar desk. Execute only the explicit approved native calendar action; no external providers or model planning.",
        model_alias="deterministic_estateflow", max_steps=1))
    result = configuration(database, principal, adapters)
    if result is None:
        raise HTTPException(409, "Calendar desk configuration is disabled or incomplete.")
    return result


def propose(database, principal, adapters, body):
    require_roles("admin", "developer")(principal)
    config = configuration(database, principal, adapters)
    if config is None:
        raise HTTPException(409, "Enable calendar actions with an active installed calendar desk first.")
    payload = (ReserveSlot if body.action == "reserve" else CancelReservation).model_validate(body.arguments)
    with database.connect() as connection:
        if body.action == "reserve":
            slot = connection.execute("SELECT * FROM estate_calendar_slots WHERE organization_id=%s AND slot_id=%s",
                (principal.organization_id, payload.slot_id)).fetchone()
            if slot is None:
                raise HTTPException(404, "Slot not found.")
            if (slot["property_id"] != payload.property_id or slot["property_version"] != payload.property_version
                    or slot["starts_at"] != payload.starts_at or slot["ends_at"] != payload.ends_at):
                raise HTTPException(409, "Proposal must match the exact offered slot.")
        elif connection.execute("SELECT 1 FROM estate_calendar_reservations WHERE organization_id=%s AND reservation_id=%s",
                (principal.organization_id, payload.reservation_id)).fetchone() is None:
            raise HTTPException(404, "Reservation not found.")
    # Separate durable steps deliberately reuse the same identity after a lost response.
    # Dynamic availability is checked at execution, never used to invalidate replay.
    run, _ = create_run(database, principal, RunCreate(agent_version_id=config["agent_version_id"],
        idempotency_key="calendar:" + body.idempotency_key,
        input={"calendar_action": body.action, "arguments": body.arguments}))
    call, _ = reserve_tool_call(database, principal, str(run["run_id"]), ToolCallReserve(
        tool_id=config["tools"][body.action], idempotency_key="calendar-call:" + body.idempotency_key,
        arguments=body.arguments))
    return call


def close(database, principal, tool_call_id):
    require_roles("admin", "worker")(principal)
    with database.connect() as connection:
        row = connection.execute("""SELECT c.*,p.contract_snapshot,a.slug,r.max_steps FROM sentinel_tool_calls c
            JOIN sentinel_runs r ON r.run_id=c.run_id AND r.organization_id=c.organization_id
            JOIN sentinel_agents a ON a.agent_id=r.agent_id AND a.organization_id=r.organization_id
            JOIN sentinel_run_tool_permissions p ON p.run_id=c.run_id AND p.tool_id=c.tool_id
                AND p.organization_id=c.organization_id
            WHERE c.organization_id=%s AND c.tool_call_id=%s""", (principal.organization_id, tool_call_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Calendar action not found.")
    if (row["slug"] != SLUG or row["max_steps"] != 1
            or not any(contract_digest(row["contract_snapshot"]) == contract_digest(contract) for contract in CONTRACTS.values())):
        raise HTTPException(409, "Only a single-action manual calendar desk run can be closed here.")
    if row["status"] == "completed":
        return finish_run(database, principal, str(row["run_id"]))
    if row["status"] in ("failed", "cancelled"):
        return cancel_run(database, principal, str(row["run_id"]), "Calendar desk closed after a failed or rejected action.")
    raise HTTPException(409, "Resolve the calendar action before closing its run.")


def queue(database, principal, adapters, limit):
    require_roles("admin", "developer", "reviewer", "worker")(principal)
    with database.connect() as connection:
        rows = connection.execute("""SELECT c.*,p.contract_snapshot,r.status AS run_status,a.slug AS agent_slug FROM sentinel_tool_calls c
            JOIN sentinel_runs r ON r.run_id=c.run_id AND r.organization_id=c.organization_id
            JOIN sentinel_agents a ON a.agent_id=r.agent_id AND a.organization_id=r.organization_id
            JOIN sentinel_run_tool_permissions p ON p.run_id=c.run_id AND p.tool_id=c.tool_id
                AND p.organization_id=c.organization_id
            WHERE c.organization_id=%s
            AND p.contract_snapshot->>'name' IN ('reserve_viewing_slot','cancel_viewing_reservation')
            AND p.contract_snapshot->>'version'='1.0.0'
            ORDER BY CASE WHEN c.status IN ('reserved','awaiting_approval','authorized','executing','unknown','needs_review')
                THEN 0 ELSE 1 END,c.created_at DESC,c.tool_call_id LIMIT %s""", (principal.organization_id, limit)).fetchall()
    calls = []
    for row in rows:
        if any(contract_digest(row["contract_snapshot"]) == contract_digest(contract) for contract in CONTRACTS.values()):
            calls.append({**tool_call_view(row), "tool_name": row["contract_snapshot"]["name"],
                "run_status": row["run_status"], "manual_desk": row["agent_slug"] == SLUG,
                "adapter_installed": adapters.supports(row["contract_snapshot"])})
    return {"configuration": configuration(database, principal, adapters), "calls": calls}
