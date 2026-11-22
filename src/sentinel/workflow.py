from typing import Any, TypedDict
from uuid import UUID

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from .model_gateway import ModelGateway, ModelRequest
from .embeddings import EmbeddingService
from .engagement import record_viewing_engagement
from .calendar_workflow import is_native_reservation, offered_slot, validate_native_decision
from .leads import workflow_lead
from .properties import search_properties
from .runs import (
    cancel_run, execute_registered_tool, finish_run, get_run, reserve_tool_call,
)
from .schemas import PropertySearch, ToolCallReserve
from .security import Principal


class EstateFlowState(TypedDict, total=False):
    run_id: str
    model_alias: str
    instructions: str
    input_payload: dict[str, Any]
    available_tools: list[dict[str, Any]]
    lead_id: str
    lead_version: int
    retrieval_id: str | None
    recommendations: list[dict[str, Any]]
    tool_id: str
    tool_arguments: dict[str, Any]
    model_explanation: str
    tool_call_id: str
    tool_call_status: str
    approval_granted: bool
    result: dict[str, Any] | None
    crm_contact_id: str
    followup_draft_id: str
    workflow_status: str


def workflow_thread_id(principal: Principal, run_id: str) -> str:
    return f"{principal.organization_id}:{run_id}"


def require_estateflow_workflow(payload: dict, model_alias: str):
    target = payload.get('workflow')
    if ((target is not None and target != 'estateflow')
            or (target is None and model_alias == 'external_agent')):
        raise HTTPException(409, 'This endpoint runs the EstateFlow example. Execute external agents through their integration.')
    # Unmarked pre-existing versions retain their legacy example behavior.


def load_workflow_input(database, principal: Principal, run_id: str) -> EstateFlowState:
    with database.connect() as connection:
        run = get_run(connection, principal.organization_id, run_id)
        version = connection.execute(
            """SELECT instructions, model_alias FROM sentinel_agent_versions
               WHERE agent_version_id=%s AND organization_id=%s""",
            (run["agent_version_id"], principal.organization_id),
        ).fetchone()
        require_estateflow_workflow(run['input_payload'], version['model_alias'])
        tools = connection.execute(
            """SELECT permission.tool_id, permission.contract_snapshot
               FROM sentinel_run_tool_permissions permission
               WHERE permission.run_id=%s AND permission.organization_id=%s
               ORDER BY permission.tool_id""",
            (run["run_id"], principal.organization_id),
        ).fetchall()
    return {
        "run_id": str(run["run_id"]),
        "model_alias": version["model_alias"],
        "instructions": version["instructions"],
        "input_payload": run["input_payload"],
        "available_tools": [
            {"tool_id": str(row["tool_id"]), **row["contract_snapshot"]} for row in tools
        ],
        "workflow_status": "planning",
    }


def build_estateflow_graph(database, principal: Principal, gateway: ModelGateway,
                           adapter, lease_seconds: int, checkpointer):
    def lead_gate(state: EstateFlowState) -> dict:
        raw_id = state["input_payload"].get("lead_id")
        if raw_id is None:
            return {"workflow_status": "planning"}
        try:
            lead_id = str(UUID(str(raw_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise HTTPException(422, "lead_id must be a UUID.") from error
        if gateway.cipher is None:
            raise HTTPException(409, "Lead credentials are not configured.")
        lead = workflow_lead(database, gateway.cipher, principal, lead_id)
        frozen_version = state["input_payload"].get("lead_version")
        native_changed = (state["input_payload"].get("native_slot_id") is not None
                          and (type(frozen_version) is not int or frozen_version != lead["version"]))
        if native_changed or lead["status"] != "qualified" or not lead["outreach_consent"]:
            cancel_run(database, principal, state["run_id"],
                       "Lead is not qualified or outreach consent is missing.")
            return {"lead_id": lead_id, "lead_version": lead["version"],
                    "workflow_status": "lead_not_ready"}
        return {"lead_id": lead_id, "lead_version": lead["version"],
                "workflow_status": "planning"}

    def current_lead(state: EstateFlowState, *, include_customer=False,
                     include_contact=False) -> dict | None:
        if "lead_id" not in state:
            return None
        lead = workflow_lead(
            database, gateway.cipher, principal, state["lead_id"],
            include_customer=include_customer, include_contact=include_contact,
        )
        if (lead["status"] != "qualified" or not lead["outreach_consent"]
                or lead["version"] != state["lead_version"]):
            cancel_run(database, principal, state["run_id"],
                       "Lead changed after workflow qualification.")
            return None
        return lead

    def retrieve(state: EstateFlowState) -> dict:
        payload = state["input_payload"]
        lead = current_lead(state)
        if "lead_id" in state and lead is None:
            return {"workflow_status": "lead_not_ready"}
        query = payload.get("property_query") or (
            lead["city"] if lead is not None else None
        )
        if payload.get("native_slot_id") is not None and not payload.get("property_query"):
            try:
                requested_slot = str(UUID(str(payload["native_slot_id"])))
            except (ValueError, TypeError, AttributeError) as error:
                raise HTTPException(422, "native_slot_id must be a UUID.") from error
            with database.connect() as connection:
                selected = connection.execute("""SELECT p.title FROM estate_calendar_slots s
                    JOIN estate_properties p ON p.property_id=s.property_id AND p.organization_id=s.organization_id
                    WHERE s.organization_id=%s AND s.slot_id=%s""",
                    (principal.organization_id, requested_slot)).fetchone()
            if selected is None:
                raise HTTPException(404, "Viewing slot not found.")
            query = selected["title"]
        if query is None:
            return {"recommendations": [], "workflow_status": "planning"}
        filters = payload.get("property_filters", {})
        if not isinstance(filters, dict):
            raise HTTPException(422, "property_filters must be an object.")
        if "query" in filters:
            raise HTTPException(422, "property_filters cannot replace property_query.")
        filters = dict(filters)
        if lead is not None:
            for key, value in (
                ("city", lead["city"]),
                ("max_price_inr", lead["max_budget_inr"]),
                ("min_bedrooms", lead["min_bedrooms"]),
            ):
                if value is not None:
                    filters[key] = value
        try:
            search = PropertySearch.model_validate({"query": query, **filters})
        except ValidationError as error:
            raise HTTPException(422, error.errors(include_context=False)) from error
        embedding_service = (
            EmbeddingService(
                database, gateway.cipher, gateway.timeout_seconds,
                gateway.client_factory,
            ) if gateway.cipher is not None else None
        )
        retrieval = search_properties(
            database, principal, search, run_id=state["run_id"],
            embedding_service=embedding_service,
        )
        recommendations = retrieval["results"]
        if not recommendations:
            cancel_run(database, principal, state["run_id"], "No matching property found.")
        return {
            "retrieval_id": retrieval["retrieval_id"],
            "recommendations": recommendations,
            "workflow_status": "planning" if recommendations else "no_match",
        }

    def plan(state: EstateFlowState) -> dict:
        lead = current_lead(state, include_customer=True)
        if "lead_id" in state and lead is None:
            return {"workflow_status": "lead_not_ready"}
        input_payload = {
            **state["input_payload"],
            "property_recommendations": state.get("recommendations", []),
        }
        if lead is not None:
            input_payload["customer"] = lead["customer"]
        native_id = input_payload.get("native_slot_id")
        native_tool = None
        tools = state["available_tools"]
        if native_id is not None:
            try:
                native_id = str(UUID(str(native_id)))
            except (ValueError, TypeError, AttributeError) as error:
                raise HTTPException(422, "native_slot_id must be a UUID.") from error
            native_tool = next((item for item in tools if is_native_reservation(item)), None)
            if native_tool is None:
                raise HTTPException(409, "This run has no exact native reservation permission.")
            arguments, available = offered_slot(database, principal, native_id, state.get("recommendations", []))
            if not available:
                cancel_run(database, principal, state["run_id"], "Requested native viewing slot is unavailable.")
                return {"workflow_status": "slot_unavailable"}
            input_payload["calendar_slot"] = arguments
            tools = [native_tool]
        decision = gateway.decide(state["model_alias"], ModelRequest(
            instructions=state["instructions"],
            input_payload=input_payload,
            available_tools=tuple(tools),
            organization_id=principal.organization_id,
            run_id=state["run_id"],
        ))
        if native_tool is not None:
            validate_native_decision(decision, native_tool, input_payload["calendar_slot"])
        elif lead is not None and (
            decision.arguments.get("customer") != lead["customer"]
        ):
            cancel_run(database, principal, state["run_id"],
                       "Model proposed a customer outside the qualified lead.")
            return {"workflow_status": "rejected"}
        if native_tool is None and decision.arguments.get("slot") != input_payload.get("slot"):
            raise HTTPException(422, "Model changed the requested viewing time.")
        selected_tool = next(item for item in state["available_tools"]
                             if str(item["tool_id"]) == decision.tool_id)
        if "property_id" in selected_tool["input_schema"].get("properties", {}):
            if not any(
                str(item["property"]["property_id"]) == decision.arguments.get("property_id")
                and item["property"]["current_version"] == decision.arguments.get("property_version")
                for item in state.get("recommendations", [])
            ):
                raise HTTPException(422, "Model selected a property outside the frozen recommendations.")
        return {
            "tool_id": decision.tool_id,
            "tool_arguments": decision.arguments,
            "model_explanation": decision.explanation,
            "workflow_status": "reserving_tool",
        }

    def reserve(state: EstateFlowState) -> dict:
        call, _ = reserve_tool_call(database, principal, state["run_id"], ToolCallReserve(
            idempotency_key=f"workflow-{state['run_id']}-book-viewing",
            tool_id=state["tool_id"],
            arguments=state["tool_arguments"],
        ))
        return {
            "tool_call_id": str(call["tool_call_id"]),
            "tool_call_status": call["status"],
            "workflow_status": (
                "waiting_approval" if call["status"] == "awaiting_approval" else "executing"
            ),
        }

    def approval(state: EstateFlowState) -> dict:
        approved = interrupt({
            "type": "tool_call_approval",
            "run_id": state["run_id"],
            "tool_call_id": state["tool_call_id"],
            "tool_id": state["tool_id"],
            "arguments": state["tool_arguments"],
        })
        return {"approval_granted": approved is True, "workflow_status": "executing"}

    def execute(state: EstateFlowState) -> dict:
        if not state.get("approval_granted", True):
            cancel_run(database, principal, state["run_id"], "Tool call rejected by reviewer.")
            return {"workflow_status": "rejected", "tool_call_status": "cancelled"}
        with database.connect() as connection:
            saved = connection.execute(
                """SELECT status, result FROM sentinel_tool_calls
                   WHERE tool_call_id=%s AND run_id=%s AND organization_id=%s""",
                (state["tool_call_id"], state["run_id"], principal.organization_id),
            ).fetchone()
        if saved is not None and saved["status"] == "completed":
            call = saved
        else:
            if "lead_id" in state and current_lead(state) is None:
                return {"workflow_status": "lead_not_ready", "tool_call_status": "cancelled"}
            arguments = state["tool_arguments"]
            if "property_id" in arguments:
                with database.connect() as connection:
                    listing = connection.execute(
                        """SELECT current_version, listing_status FROM estate_properties
                           WHERE property_id=%s AND organization_id=%s""",
                        (arguments["property_id"], principal.organization_id),
                    ).fetchone()
                if (listing is None or listing["listing_status"] != "active"
                        or listing["current_version"] != arguments["property_version"]):
                    cancel_run(database, principal, state["run_id"], "Approved property changed before booking.")
                    return {"workflow_status": "rejected", "tool_call_status": "cancelled"}
            call = execute_registered_tool(
                database, principal, state["run_id"], state["tool_call_id"],
                adapter, lease_seconds,
            )
        if (call["status"] == "completed" and "slot_id" in state["tool_arguments"]
                and call["result"].get("status") != "confirmed"):
            cancel_run(database, principal, state["run_id"], "Native viewing reservation was unavailable.")
            return {"tool_call_status": "completed", "result": call["result"],
                    "workflow_status": "slot_unavailable"}
        return {
            "tool_call_status": call["status"],
            "result": call["result"],
            "workflow_status": (
                "completed" if call["status"] == "completed" else call["status"]
            ),
        }

    def engage(state: EstateFlowState) -> dict:
        additions = {}
        if "lead_id" in state:
            lead = workflow_lead(
                database, gateway.cipher, principal, state["lead_id"],
                include_customer=True, include_contact=True
            )
            additions = record_viewing_engagement(
                database, gateway.cipher, principal, state["run_id"], lead,
                state.get("recommendations", []), state["result"],
                state["tool_arguments"],
                expected_lead_version=state["lead_version"],
            )
        finish_run(database, principal, state["run_id"])
        return {**additions, "workflow_status": "completed"}

    def after_reservation(state: EstateFlowState) -> str:
        return "approval" if state["tool_call_status"] == "awaiting_approval" else "execute"

    def after_retrieval(state: EstateFlowState) -> str:
        return "done" if state["workflow_status"] in (
            "no_match", "lead_not_ready"
        ) else "plan"

    def after_lead_gate(state: EstateFlowState) -> str:
        return "done" if state["workflow_status"] == "lead_not_ready" else "retrieve"

    def after_plan(state: EstateFlowState) -> str:
        return "done" if state["workflow_status"] in (
            "lead_not_ready", "rejected", "slot_unavailable"
        ) else "reserve"

    def after_execute(state: EstateFlowState) -> str:
        return "engage" if state["workflow_status"] == "completed" else "done"

    builder = StateGraph(EstateFlowState)
    builder.add_node("lead_gate", lead_gate)
    builder.add_node("retrieve", retrieve)
    builder.add_node("plan", plan)
    builder.add_node("reserve", reserve)
    builder.add_node("approval", approval)
    builder.add_node("execute", execute)
    builder.add_node("engage", engage)
    builder.add_edge(START, "lead_gate")
    builder.add_conditional_edges(
        "lead_gate", after_lead_gate, {"done": END, "retrieve": "retrieve"}
    )
    builder.add_conditional_edges(
        "retrieve", after_retrieval, {"done": END, "plan": "plan"}
    )
    builder.add_conditional_edges(
        "plan", after_plan, {"done": END, "reserve": "reserve"}
    )
    builder.add_conditional_edges(
        "reserve", after_reservation, {"approval": "approval", "execute": "execute"}
    )
    builder.add_edge("approval", "execute")
    builder.add_conditional_edges(
        "execute", after_execute, {"engage": "engage", "done": END}
    )
    builder.add_edge("engage", END)
    return builder.compile(checkpointer=checkpointer)


def workflow_view(state: dict, principal: Principal, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "thread_id": workflow_thread_id(principal, run_id),
        "status": state.get("workflow_status", "not_started"),
        "model_alias": state.get("model_alias"),
        "lead_id": state.get("lead_id"),
        "lead_version": state.get("lead_version"),
        "retrieval_id": state.get("retrieval_id"),
        "recommendations": state.get("recommendations", []),
        "tool_call_id": state.get("tool_call_id"),
        "model_explanation": state.get("model_explanation"),
        "result": state.get("result"),
        "crm_contact_id": state.get("crm_contact_id"),
        "followup_draft_id": state.get("followup_draft_id"),
    }


def start_workflow(database, principal: Principal, run_id: str, gateway: ModelGateway,
                   adapter, lease_seconds: int, checkpointer) -> dict:
    initial = load_workflow_input(database, principal, run_id)
    graph = build_estateflow_graph(
        database, principal, gateway, adapter, lease_seconds, checkpointer
    )
    config = {"configurable": {"thread_id": workflow_thread_id(principal, run_id)}}
    snapshot = graph.get_state(config)
    if snapshot.values:
        if snapshot.values.get("tool_call_id") or not snapshot.next:
            return workflow_view(snapshot.values, principal, run_id)
        graph.invoke(None, config)
    else:
        graph.invoke(initial, config)
    return workflow_view(graph.get_state(config).values, principal, run_id)


def resume_workflow(database, principal: Principal, run_id: str, gateway: ModelGateway,
                    adapter, lease_seconds: int, checkpointer) -> dict:
    # This organization-scoped read prevents checkpoint thread IDs from becoming an
    # authorization mechanism.
    load_workflow_input(database, principal, run_id)
    graph = build_estateflow_graph(
        database, principal, gateway, adapter, lease_seconds, checkpointer
    )
    config = {"configurable": {"thread_id": workflow_thread_id(principal, run_id)}}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        raise HTTPException(409, "Workflow has not been started.")
    if not snapshot.next:
        return workflow_view(snapshot.values, principal, run_id)
    if snapshot.next == ("engage",):
        graph.invoke(None, config)
        return workflow_view(graph.get_state(config).values, principal, run_id)
    call_id = snapshot.values.get("tool_call_id")
    with database.connect() as connection:
        call = connection.execute(
            """SELECT status FROM sentinel_tool_calls
               WHERE tool_call_id=%s AND run_id=%s AND organization_id=%s""",
            (call_id, run_id, principal.organization_id),
        ).fetchone()
    if call is None:
        raise HTTPException(404, "Workflow tool call not found.")
    if call["status"] == "cancelled":
        graph.invoke(Command(resume=False), config)
        return workflow_view(graph.get_state(config).values, principal, run_id)
    if call["status"] not in ("authorized", "completed"):
        raise HTTPException(409, "Sentinel approval is required before workflow resume.")
    graph.invoke(Command(resume=True), config)
    return workflow_view(graph.get_state(config).values, principal, run_id)
