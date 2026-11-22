"""Native HTTP/PostgreSQL calendar, competing bookings, cancellation and lost replies."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres
from sentinel.adapters import AdapterContext
from sentinel.booking_adapter import EvidenceMismatch
from sentinel.calendar import CalendarAdapter, NativeCalendar, RESERVE_CONTRACT, CANCEL_CONTRACT
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.runs import claim_tool_call
from sentinel.security import Principal, digest_key


def main():
    print("CHECK: native calendar setup and manual actions", flush=True)
    dev.setup()
    config = dev.load_config()
    app = create_app(Settings(database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002", credential_encryption_key=config["credential_encryption_key"]))
    http = TestClient(app)
    headers = {role: {"X-API-Key": config["keys"][role]} for role in config["keys"]}
    marker = uuid4().hex

    def post(path, body, role="developer", expected=(200, 201)):
        response = http.post(path, json=body, headers=headers[role])
        assert response.status_code in expected, f"Unexpected status {response.status_code} at {path}."
        return response.json()

    listing = {"external_key": "calendar-" + marker, "title": "Fictional scheduling apartment",
        "description": "Fictional native calendar fixture, not a real listing.", "city": "Jaipur",
        "locality": "Mansarovar", "property_type": "apartment", "price_inr": "7500000.00",
        "amenities": [], "source_uri": "https://estateflow.example.test/calendar/" + marker,
        "listing_status": "active"}
    prop = post("/v1/properties", listing)["property"]
    start = (datetime.now(timezone.utc) + timedelta(days=14)).replace(second=0, microsecond=0)

    def offer(minutes, duration=30):
        body = {"property_id": prop["property_id"], "property_version": prop["current_version"],
            "starts_at": (start + timedelta(minutes=minutes)).isoformat(),
            "ends_at": (start + timedelta(minutes=minutes + duration)).isoformat()}
        return post("/v1/calendar/slots", body), body

    slot1, body1 = offer(0)
    slot2, body2 = offer(15)
    assert post("/v1/calendar/slots", body1)["slot_id"] == slot1["slot_id"]
    assert http.post("/v1/calendar/slots", json=body1, headers=headers["reviewer"]).status_code == 403
    assert http.get("/v1/calendar/slots", headers=headers["worker"]).status_code == 403
    agent = post("/v1/agents", {"slug": "calendar_" + marker, "display_name": "Native scheduling acceptance"})
    tools = {}
    for contract in (RESERVE_CONTRACT, CANCEL_CONTRACT):
        tool = post("/v1/tools", contract)
        tools[contract["name"]] = tool
        post(f"/v1/agents/{agent['agent_id']}/tools/{tool['tool_id']}", {"max_calls_per_run": 2})
    version = post(f"/v1/agents/{agent['agent_id']}/versions", {"version": "1.0.0",
        "instructions": "Native calendar acceptance; do not contact external providers.",
        "model_alias": "deterministic_estateflow", "max_steps": 8})

    def call(name, arguments):
        run = post("/v1/runs", {"agent_version_id": version["agent_version_id"],
            "idempotency_key": uuid4().hex, "input": {"fictional_calendar": True}})
        result = post(f"/v1/runs/{run['run_id']}/tool-calls", {"tool_id": tools[name]["tool_id"],
            "idempotency_key": uuid4().hex, "arguments": arguments}, "worker")
        base = f"/v1/runs/{run['run_id']}/tool-calls/{result['tool_call_id']}"
        assert http.post(base + "/execute", json={}, headers=headers["worker"]).status_code == 409
        post(base + "/approve", {"valid_for_seconds": 300}, "reviewer")
        return run, result, base

    validation_run = post("/v1/runs", {"agent_version_id": version["agent_version_id"],
        "idempotency_key": "redaction_" + marker, "input": {"fictional_security_fixture": True}})
    private_marker = "PRIVATE_TOOL_VALIDATION_CANARY"
    invalid = http.post(f"/v1/runs/{validation_run['run_id']}/tool-calls", json={
        "tool_id": tools["reserve_viewing_slot"]["tool_id"], "idempotency_key": "invalid_" + marker,
        "arguments": {"slot_id": slot1["slot_id"], **body1, private_marker: private_marker}}, headers=headers["worker"])
    assert invalid.status_code == 422 and private_marker not in invalid.text
    assert invalid.json()["detail"]["path"] == "$"
    assert http.get(f"/v1/runs/{validation_run['run_id']}/tool-calls", headers=headers["developer"]).json() == []
    first = call("reserve_viewing_slot", {"slot_id": slot1["slot_id"], **body1})
    second = call("reserve_viewing_slot", {"slot_id": slot2["slot_id"], **body2})
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda item: post(item[2] + "/execute", {}, "worker"), (first, second)))
    assert all(outcome["status"] == "completed" for outcome in outcomes)
    assert sorted(outcome["result"]["status"] for outcome in outcomes) == ["confirmed", "unavailable"]
    winner_index = next(i for i, outcome in enumerate(outcomes) if outcome["result"]["status"] == "confirmed")
    winner, loser = (first, second)[winner_index], (first, second)[1 - winner_index]
    winner_result = outcomes[winner_index]["result"]
    with app.state.database.connect() as connection:
        key = connection.execute("SELECT api_key_id,organization_id,role FROM sentinel_api_keys WHERE key_digest=%s",
            (digest_key(config["keys"]["worker"], config["auth_pepper"]),)).fetchone()
    principal = Principal(**{name: str(value) for name, value in key.items()})
    context = AdapterContext(principal.organization_id, winner[0]["run_id"], winner[1]["tool_call_id"],
                            winner[1]["arguments"], RESERVE_CONTRACT)
    recreated = CalendarAdapter(NativeCalendar(app.state.database), "reserve")
    assert recreated.reconcile(context).result == winner_result
    assert recreated.execute(context).result == winner_result
    try:
        recreated.reconcile(AdapterContext(context.organization_id, context.run_id, context.tool_call_id,
            {**context.arguments, "property_version": 999}, RESERVE_CONTRACT))
        raise AssertionError("Changed receipt arguments were accepted.")
    except EvidenceMismatch:
        pass
    cancel = call("cancel_viewing_reservation", {"reservation_id": winner_result["reservation_id"]})
    cancelled = post(cancel[2] + "/execute", {}, "worker")
    assert cancelled["result"]["status"] == "cancelled"
    assert recreated.reconcile(context).result == winner_result  # Historical decision remains immutable.
    loser_args = loser[1]["arguments"]
    fresh = call("reserve_viewing_slot", loser_args)
    assert post(fresh[2] + "/execute", {}, "worker")["result"]["status"] == "confirmed"
    loser_context = AdapterContext(principal.organization_id, loser[0]["run_id"], loser[1]["tool_call_id"], loser_args, RESERVE_CONTRACT)
    assert recreated.execute(loser_context).result == {"status": "unavailable", "reservation_id": None}

    slot3, body3 = offer(60)
    lost = call("reserve_viewing_slot", {"slot_id": slot3["slot_id"], **body3})
    claimed = claim_tool_call(app.state.database, principal, lost[0]["run_id"], lost[1]["tool_call_id"], 30, app.state.tool_adapters)
    lost_context = AdapterContext(principal.organization_id, lost[0]["run_id"], lost[1]["tool_call_id"], claimed["arguments"], RESERVE_CONTRACT)
    recreated.execute(lost_context)  # Commit the decision, discard the reply, abandon the ledger lease.
    with app.state.database.connect() as connection:
        connection.execute("UPDATE sentinel_tool_calls SET lease_expires_at=now()-interval '1 second' WHERE tool_call_id=%s", (lost[1]["tool_call_id"],))
    recovered = post(lost[2] + "/reconcile", {}, "worker")
    assert recovered["status"] == "completed" and recovered["result"]["status"] == "confirmed"
    slot4, body4 = offer(120)
    post(f"/v1/calendar/slots/{slot4['slot_id']}/withdraw", {})
    withdrawn = call("reserve_viewing_slot", {"slot_id": slot4["slot_id"], **body4})
    assert post(withdrawn[2] + "/execute", {}, "worker")["result"]["status"] == "unavailable"
    slot5, body5 = offer(180)
    stale = call("reserve_viewing_slot", {"slot_id": slot5["slot_id"], **body5})
    post("/v1/properties", {**listing, "listing_status": "inactive"})
    assert post(stale[2] + "/execute", {}, "worker")["result"]["status"] == "unavailable"
    with app.state.database.connect() as connection:
        count = connection.execute("""SELECT count(*) AS count FROM estate_calendar_reservations r
            JOIN estate_calendar_slots s USING(slot_id,organization_id) WHERE s.property_id=%s""", (prop["property_id"],)).fetchone()["count"]
    assert count == 3
    # The dashboard's purpose-specific developer proposal boundary must preserve
    # the ordinary worker-only tool reservation and exact-action approval policy.
    desk = post("/v1/calendar/configuration", {})
    assert post("/v1/calendar/configuration", {}) == desk
    for role in ("reviewer", "worker"):
        assert http.post("/v1/calendar/configuration", json={}, headers=headers[role]).status_code == 403
    prop = post("/v1/properties", listing)["property"]  # Reactivate with a new version.
    desk_slot, desk_body = offer(240)
    proposal = {"action": "reserve", "idempotency_key": "desk_" + marker,
        "arguments": {"slot_id": desk_slot["slot_id"], **desk_body}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        duplicates = list(pool.map(lambda _: post("/v1/calendar/proposals", proposal), range(2)))
    desk_call = duplicates[0]
    assert duplicates[1]["tool_call_id"] == desk_call["tool_call_id"]
    assert desk_call["status"] == "awaiting_approval" and desk_call["requires_approval"]
    desk_base = f"/v1/runs/{desk_call['run_id']}/tool-calls/{desk_call['tool_call_id']}"
    assert http.post(f"/v1/calendar/actions/{desk_call['tool_call_id']}/close", json={}, headers=headers["worker"]).status_code == 409
    assert http.post("/v1/calendar/proposals", json={**proposal, "arguments": {"slot_id": slot1["slot_id"], **body1}}, headers=headers["developer"]).status_code == 409
    assert http.post(desk_base + "/execute", json={}, headers=headers["worker"]).status_code == 409
    assert http.post(desk_base + "/approve", json={}, headers=headers["developer"]).status_code == 403
    for role in ("reviewer", "worker"):
        assert http.post("/v1/calendar/proposals", json=proposal, headers=headers[role]).status_code == 403
    assert http.post(f"/v1/runs/{desk_call['run_id']}/tool-calls", json={"tool_id": desk_call["tool_id"],
        "idempotency_key": "generic_" + marker, "arguments": proposal["arguments"]}, headers=headers["developer"]).status_code == 403
    assert http.post("/v1/calendar/proposals", json={**proposal, "arguments": {**proposal["arguments"], "property_version": prop["current_version"] + 1}}, headers=headers["developer"]).status_code == 409
    post(desk_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
    post(desk_base + "/revoke", {}, "reviewer")
    assert http.post(desk_base + "/execute", json={}, headers=headers["worker"]).status_code == 409
    post(desk_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
    booked = post(desk_base + "/execute", {}, "worker")
    assert booked["result"]["status"] == "confirmed"
    assert http.post(f"/v1/calendar/actions/{desk_call['tool_call_id']}/close", json={}, headers=headers["developer"]).status_code == 403
    assert post(f"/v1/calendar/actions/{desk_call['tool_call_id']}/close", {}, "worker")["status"] == "succeeded"
    assert post("/v1/calendar/proposals", proposal)["tool_call_id"] == desk_call["tool_call_id"]
    cancel_proposal = {"action": "cancel", "idempotency_key": "desk_cancel_" + marker,
        "arguments": {"reservation_id": booked["result"]["reservation_id"]}}
    cancel_call = post("/v1/calendar/proposals", cancel_proposal)
    assert http.post("/v1/calendar/proposals", json={**cancel_proposal, "idempotency_key": proposal["idempotency_key"]}, headers=headers["developer"]).status_code == 409
    cancel_base = f"/v1/runs/{cancel_call['run_id']}/tool-calls/{cancel_call['tool_call_id']}"
    post(cancel_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
    assert post(cancel_base + "/execute", {}, "worker")["result"]["status"] == "cancelled"
    for role in ("developer", "reviewer", "worker"):
        actions = http.get("/v1/calendar/actions?limit=100", headers=headers[role]).json()
        entry = next(item for item in actions["calls"] if item["tool_call_id"] == desk_call["tool_call_id"])
        assert entry["result"]["status"] == "confirmed" and entry["run_status"] == "succeeded"
    rejected = post("/v1/calendar/proposals", {**proposal, "idempotency_key": "desk_reject_" + marker})
    reject_base = f"/v1/runs/{rejected['run_id']}/tool-calls/{rejected['tool_call_id']}"
    assert post(reject_base + "/reject", {}, "reviewer")["status"] == "cancelled"
    assert post(f"/v1/calendar/actions/{rejected['tool_call_id']}/close", {}, "worker")["status"] == "cancelled"
    assert http.post(f"/v1/calendar/actions/{first[1]['tool_call_id']}/close", json={}, headers=headers["worker"]).status_code == 409
    foreign_org, foreign_key = uuid4(), uuid4()
    prefix = "snt_" + uuid4().hex
    token = prefix + "_" + uuid4().hex
    with app.state.database.connect() as connection:
        connection.execute("INSERT INTO sentinel_organizations(organization_id,name) VALUES (%s,%s)", (foreign_org, "Fictional calendar isolation tenant"))
        connection.execute("""INSERT INTO sentinel_api_keys(api_key_id,organization_id,key_prefix,key_digest,label,role)
            VALUES (%s,%s,%s,%s,%s,'developer')""", (foreign_key, foreign_org, prefix, digest_key(token, config["auth_pepper"]), "Calendar isolation key"))
    try:
        foreign = {"X-API-Key": token}
        assert http.get("/v1/calendar/slots", headers=foreign).json() == []
        assert http.get("/v1/calendar/reservations", headers=foreign).json() == []
        assert http.get("/v1/calendar/actions", headers=foreign).json() == {"configuration": None, "calls": []}
        http.post("/v1/calendar/configuration", json={}, headers=foreign).raise_for_status()
        assert http.post("/v1/calendar/proposals", json=proposal, headers=foreign).status_code == 404
        assert http.post("/v1/calendar/proposals", json=cancel_proposal, headers=foreign).status_code == 404
        assert http.post(f"/v1/calendar/actions/{desk_call['tool_call_id']}/close", json={}, headers=foreign).status_code == 403
        assert http.post(f"/v1/calendar/slots/{slot1['slot_id']}/withdraw", json={}, headers=foreign).status_code == 404
    finally:
        with app.state.database.connect() as connection:
            # The temporary organization now owns a configured desk. Keep its
            # tenant fixture and revoke its key instead of deleting FK-bound rows.
            connection.execute("UPDATE sentinel_api_keys SET revoked_at=now() WHERE api_key_id=%s", (foreign_key,))
        http.close()
    from native_workflow_checks import exercise_native_workflow
    exercise_native_workflow(app, headers, marker, principal)
    print("PASS: timezone-aware offers, value-free tool validation, exact approvals, competing overlapping slots, durable decision replay, cancellation, fresh approved rebooking, lost-reply recovery, withdrawn/stale listings, idempotent developer proposals, role boundaries, review/revocation, manual run closure, and tenant isolation.")


if __name__ == "__main__":
    main()
