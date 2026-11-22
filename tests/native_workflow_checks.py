"""Real PostgreSQL/checkpoint checks used by native calendar acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sentinel.adapters import AdapterContext
from sentinel.calendar import CalendarAdapter, NativeCalendar, RESERVE_CONTRACT
from sentinel.main import create_app
from sentinel.runs import claim_tool_call


def exercise_native_workflow(app, headers, marker, principal):
    print("CHECK: automatic native workflow startup", flush=True)
    with TestClient(app) as http:
        def post(path, body=None, role="developer", expected=(200, 201)):
            response = http.post(path, json={} if body is None else body, headers=headers[role])
            assert response.status_code in expected, f"Unexpected status {response.status_code} at {path}."
            return response.json()

        config = post("/v1/calendar/workflow/configuration")
        assert post("/v1/calendar/workflow/configuration") == config
        for role in ("reviewer", "worker"):
            post("/v1/calendar/workflow/configuration", role=role, expected=(403,))
        listing = {"external_key": "native-workflow-" + marker, "title": "Nativeworkflow" + marker,
            "description": "Fictional automatic native scheduling acceptance fixture.", "city": "Jaipur",
            "locality": "Mansarovar", "property_type": "apartment", "price_inr": "7500000.00",
            "amenities": [], "source_uri": "https://estateflow.example.test/native/" + marker,
            "listing_status": "active"}
        prop = post("/v1/properties", listing)["property"]
        start = (datetime.now(timezone.utc) + timedelta(days=20)).replace(second=0, microsecond=0)

        def offer(minutes):
            return post("/v1/calendar/slots", {"property_id": prop["property_id"],
                "property_version": prop["current_version"],
                "starts_at": (start + timedelta(minutes=minutes)).isoformat(),
                "ends_at": (start + timedelta(minutes=minutes + 30)).isoformat()})

        def lead():
            suffix = uuid4().hex
            return post("/v1/leads", {"external_key": "native-lead-" + suffix,
                "customer_name": "Fictional native buyer", "channel": "manual",
                "contact_email": suffix + "@example.test", "city": "Jaipur",
                "max_budget_inr": "9000000.00", "timeline": "within_month",
                "outreach_consent": True})["lead"]

        def pause(slot):
            buyer = lead()
            body = {"idempotency_key": "native-run-" + uuid4().hex,
                    "agent_version_id": config["agent_version_id"], "native_slot_id": slot["slot_id"]}
            run = post(f"/v1/leads/{buyer['lead_id']}/runs", body)
            assert post(f"/v1/leads/{buyer['lead_id']}/runs", body)["run_id"] == run["run_id"]
            post(f"/v1/leads/{buyer['lead_id']}/runs", {**body, "native_slot_id": str(uuid4())}, expected=(409,))
            root = f"/v1/runs/{run['run_id']}"
            state = post(root + "/workflow/start", role="worker")
            assert state["status"] == "waiting_approval" and state["lead_id"] == buyer["lead_id"]
            calls = http.get(root + "/tool-calls", headers=headers["developer"]).json()
            assert len(calls) == 1 and calls[0]["tool_id"] == config["tool_id"]
            assert calls[0]["arguments"]["slot_id"] == slot["slot_id"]
            assert calls[0]["arguments"]["property_id"] == prop["property_id"]
            assert "customer" not in calls[0]["arguments"]
            call_path = root + "/tool-calls/" + state["tool_call_id"]
            post(call_path + "/execute", role="worker", expected=(409,))
            return {"run": run, "lead": buyer, "root": root, "call": calls[0], "path": call_path}

        def approve(item):
            post(item["path"] + "/approve", {"valid_for_seconds": 300}, "reviewer")

        def resume(item):
            return post(item["root"] + "/workflow/resume", role="worker")

        def cancel(reservation_id):
            post("/v1/calendar/configuration")
            call = post("/v1/calendar/proposals", {"action": "cancel",
                "idempotency_key": "native-cancel-" + uuid4().hex,
                "arguments": {"reservation_id": reservation_id}})
            path = f"/v1/runs/{call['run_id']}/tool-calls/{call['tool_call_id']}"
            post(path + "/approve", {"valid_for_seconds": 300}, "reviewer")
            assert post(path + "/execute", role="worker")["result"]["status"] == "cancelled"
            post(f"/v1/calendar/actions/{call['tool_call_id']}/close", role="worker")

        slot = offer(0)
        print("CHECK: native workflow planning and exact approvals", flush=True)
        first, second = pause(slot), pause(slot)
        post(first["path"] + "/approve", {"valid_for_seconds": 300}, "developer", expected=(403,))
        approve(first)
        approve(second)
        print("CHECK: concurrent native workflow resumes", flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(resume, (first, second)))
        assert sorted(result["status"] for result in results) == ["completed", "slot_unavailable"]
        winner_index = next(index for index, result in enumerate(results) if result["status"] == "completed")
        winner, loser = (first, second)[winner_index], (first, second)[1 - winner_index]
        done = results[winner_index]
        assert done["result"]["status"] == "confirmed" and done["crm_contact_id"] and done["followup_draft_id"]
        assert http.get(loser["root"], headers=headers["developer"]).json()["status"] == "cancelled"
        assert not results[1 - winner_index]["crm_contact_id"] and not results[1 - winner_index]["followup_draft_id"]
        draft = next(row for row in http.get("/v1/followups?limit=100", headers=headers["developer"]).json()
                     if row["draft_id"] == done["followup_draft_id"])
        assert draft["context_snapshot"]["reservation_id"] == done["result"]["reservation_id"]
        assert prop["title"] in draft["body"] and done["result"]["reservation_id"] in draft["body"]
        post(f"/v1/followups/{draft['draft_id']}/approve", {"expected_revision": draft["revision"]}, "reviewer")
        assert resume(winner)["followup_draft_id"] == done["followup_draft_id"]
        cancel(done["result"]["reservation_id"])
        outcomes = http.get(winner["root"] + "/engagement", headers=headers["developer"]).json()
        assert outcomes["reservation"]["status"] == "cancelled" and outcomes["review_required"]
        assert outcomes["followup"]["status"] == "cancelled" and outcomes["delivery"]["status"] == "not_sent"
        post(f"/v1/followups/{draft['draft_id']}/approve", {"expected_revision": draft["revision"]}, "reviewer", expected=(409,))
        contact = next(row for row in http.get("/v1/crm/contacts?limit=100", headers=headers["developer"]).json()
                       if row["crm_contact_id"] == done["crm_contact_id"])
        assert contact["stage"] == "human_review"
        print("CHECK: native workflow rejection, lead changes and expiry", flush=True)

        rejected = pause(offer(60))
        post(rejected["path"] + "/reject", role="reviewer")
        assert resume(rejected)["status"] == "rejected"
        changed_lead = pause(offer(120))
        approve(changed_lead)
        post(f"/v1/leads/{changed_lead['lead']['lead_id']}/handoff", {"reason_code": "customer_requested"}, "reviewer")
        assert resume(changed_lead)["status"] == "lead_not_ready"
        # Direct worker execution must enforce the frozen lead binding too.
        changed_direct = pause(offer(480))
        approve(changed_direct)
        post(f"/v1/leads/{changed_direct['lead']['lead_id']}/handoff", {"reason_code": "customer_requested"}, "reviewer")
        replay = post(f"/v1/leads/{changed_direct['lead']['lead_id']}/runs", {
            "idempotency_key": changed_direct["run"]["idempotency_key"],
            "agent_version_id": config["agent_version_id"],
            "native_slot_id": changed_direct["run"]["input"]["native_slot_id"]})
        assert replay["run_id"] == changed_direct["run"]["run_id"]
        direct = post(changed_direct["path"] + "/execute", role="worker")
        assert direct["result"] == {"status": "unavailable", "reservation_id": None}
        assert resume(changed_direct)["status"] == "slot_unavailable"
        withdrawn_slot = offer(180)
        withdrawn = pause(withdrawn_slot)
        approve(withdrawn)
        post(f"/v1/calendar/slots/{withdrawn_slot['slot_id']}/withdraw")
        assert resume(withdrawn)["status"] == "slot_unavailable"
        buyer = lead()
        early = post(f"/v1/leads/{buyer['lead_id']}/runs", {
            "idempotency_key": "native-early-" + uuid4().hex,
            "agent_version_id": config["agent_version_id"], "native_slot_id": withdrawn_slot["slot_id"]})
        early_root = f"/v1/runs/{early['run_id']}"
        assert post(early_root + "/workflow/start", role="worker")["status"] == "slot_unavailable"
        assert http.get(early_root + "/tool-calls", headers=headers["developer"]).json() == []
        post(f"/v1/leads/{buyer['lead_id']}/runs", {"idempotency_key": "native-wrong-path-" + uuid4().hex,
            "agent_version_id": config["agent_version_id"], "slot": start.isoformat()}, expected=(409,))
        expired = pause(offer(240))
        approve(expired)
        with app.state.database.connect() as connection:
            connection.execute("UPDATE sentinel_tool_call_approvals SET expires_at=now()-interval '1 second' WHERE tool_call_id=%s",
                               (expired["call"]["tool_call_id"],))
        post(expired["path"] + "/execute", role="worker", expected=(409,))
        post(expired["path"] + "/reject", role="reviewer")
        assert resume(expired)["status"] == "rejected"
        before_engage = pause(offer(300))
        approve(before_engage)
        receipt = post(before_engage["path"] + "/execute", role="worker")["result"]
        cancel(receipt["reservation_id"])
        after_cancel = resume(before_engage)
        assert after_cancel["status"] == "completed" and after_cancel["crm_contact_id"]
        assert after_cancel["followup_draft_id"] is None
        assert http.get(before_engage["root"] + "/engagement", headers=headers["developer"]).json()["review_required"]

        recovery = pause(offer(360))
        approve(recovery)
        claimed = claim_tool_call(app.state.database, principal, recovery["run"]["run_id"],
                                  recovery["call"]["tool_call_id"], 30, app.state.tool_adapters)
        context = AdapterContext(principal.organization_id, recovery["run"]["run_id"],
            recovery["call"]["tool_call_id"], claimed["arguments"], RESERVE_CONTRACT)
        committed = CalendarAdapter(NativeCalendar(app.state.database), "reserve").execute(context).result
        with app.state.database.connect() as connection:
            connection.execute("UPDATE sentinel_tool_calls SET lease_expires_at=now()-interval '1 second' WHERE tool_call_id=%s",
                               (recovery["call"]["tool_call_id"],))
        stale = pause(offer(540))
        approve(stale)
        post("/v1/properties", {**listing, "price_inr": "7500001.00"})
        assert resume(stale)["status"] == "rejected"
        buyer = lead()
        stale_early = post(f"/v1/leads/{buyer['lead_id']}/runs", {
            "idempotency_key": "native-stale-early-" + uuid4().hex,
            "agent_version_id": config["agent_version_id"],
            "native_slot_id": stale["run"]["input"]["native_slot_id"]})
        stale_root = f"/v1/runs/{stale_early['run_id']}"
        assert post(stale_root + "/workflow/start", role="worker")["status"] == "slot_unavailable"
        assert http.get(stale_root + "/tool-calls", headers=headers["developer"]).json() == []

    # Replace the application and checkpoint connection after the lost reply.
    restarted = create_app(app.state.settings)
    print("CHECK: native workflow fresh application and receipt recovery", flush=True)
    with TestClient(restarted) as http:
        recovered = post(recovery["path"] + "/reconcile", role="worker")
        assert recovered["result"] == committed and recovered["status"] == "completed"
        done = resume(recovery)
        assert done["status"] == "completed" and done["result"] == committed
        assert done["crm_contact_id"] and done["followup_draft_id"]
        assert resume(recovery)["followup_draft_id"] == done["followup_draft_id"]
        with restarted.state.database.connect() as connection:
            assert connection.execute("SELECT count(*) AS n FROM estate_calendar_reservations WHERE run_id=%s",
                (recovery["run"]["run_id"],)).fetchone()["n"] == 1
            assert connection.execute("SELECT count(*) AS n FROM estate_followup_drafts WHERE run_id=%s",
                (recovery["run"]["run_id"],)).fetchone()["n"] == 1
    print("PASS: automatic native viewing workflow, competing buyers, exact review, expiry, changed leads, cancellation linkage and checkpoint/lost-reply recovery.")
