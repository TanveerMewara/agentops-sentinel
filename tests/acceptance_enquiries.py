"""Real PostgreSQL + in-process HTTP checks for the website-to-run entry flow."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app


def main():
    dev.setup()
    config = dev.load_config()
    app = create_app(Settings(
        database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002",
        credential_encryption_key=config["credential_encryption_key"],
    ))
    client = TestClient(app)
    developer = {"X-API-Key": config["keys"]["developer"]}
    reviewer = {"X-API-Key": config["keys"]["reviewer"]}
    worker = {"X-API-Key": config["keys"]["worker"]}
    marker = uuid4().hex
    lead = {
        "external_key": f"enquiry-{marker}", "channel": "website",
        "customer_name": "Fictional Buyer", "contact_email": "buyer@example.test",
        "city": "Jaipur", "max_budget_inr": "15000000.00",
        "timeline": "within_month", "outreach_consent": True,
    }
    body = {"delivery_key": f"delivery-{marker}", "source_sequence": 1, "lead": lead}
    endpoint = "/v1/enquiries/website"
    assert client.post(endpoint, headers=reviewer, json=body).status_code == 403
    first = client.post(endpoint, headers=developer, json=body)
    assert first.status_code == 201, first.text
    receipt = first.json()
    replay = client.post(endpoint, headers=developer, json=body)
    assert replay.status_code == 200 and replay.json() == receipt
    changed = {**body, "lead": {**lead, "city": "Delhi"}}
    assert client.post(endpoint, headers=developer, json=changed).status_code == 409
    newer = {**body, "delivery_key": f"newer-{marker}", "source_sequence": 3,
             "lead": {**lead, "city": "Delhi"}}
    updated = client.post(endpoint, headers=developer, json=newer)
    assert updated.status_code == 201 and updated.json()["lead_version"] == 2
    stale = {**body, "delivery_key": f"stale-{marker}", "source_sequence": 2}
    assert client.post(endpoint, headers=developer, json=stale).status_code == 409
    assert client.post(endpoint, headers=developer, json=body).json() == receipt
    current = client.get(f"/v1/leads/{receipt['lead_id']}", headers=developer).json()
    assert current["city"] == "Delhi" and current["current_version"] == 2
    concurrent = {**body, "delivery_key": f"concurrent-{marker}", "source_sequence": 1,
                  "lead": {**lead, "external_key": f"parallel-{marker}"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(
            endpoint, headers=developer, json=concurrent), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    agent = client.post("/v1/agents", headers=developer, json={
        "slug": f"enquiry_{marker[:12]}", "display_name": "Enquiry acceptance",
        "description": "Acceptance entry flow",
    })
    assert agent.status_code == 201, agent.text
    tool = client.post("/v1/tools", headers=developer, json={
        "name": "book_viewing", "version": "1.0.0",
        "description": "Creates one approved property viewing.",
        "input_schema": {"type": "object", "properties": {
            "customer": {"type": "string", "minLength": 1},
            "slot": {"type": "string", "minLength": 1}},
            "required": ["customer", "slot"], "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {
            "booking_id": {"type": "string", "minLength": 1}},
            "required": ["booking_id"], "additionalProperties": False},
        "risk_level": "high", "approval_mode": "always",
    })
    assert tool.status_code in (200, 201), tool.text
    grant = client.post(f"/v1/agents/{agent.json()['agent_id']}/tools/{tool.json()['tool_id']}",
                        headers=developer, json={"max_calls_per_run": 1})
    assert grant.status_code == 200, grant.text
    version = client.post(f"/v1/agents/{agent.json()['agent_id']}/versions",
        headers=developer, json={"version": "1.0.0", "instructions": "Arrange a viewing.",
                                "model_alias": "deterministic_estateflow"})
    assert version.status_code == 201, version.text
    run_body = {"idempotency_key": f"launch-{marker}",
                "agent_version_id": version.json()["agent_version_id"],
                "slot": "2030-05-01T10:00:00Z"}
    path = f"/v1/leads/{receipt['lead_id']}/runs"
    run = client.post(path, headers=developer, json=run_body)
    assert run.status_code == 201, run.text
    assert run.json()["input"]["lead_id"] == receipt["lead_id"]
    assert client.post(path, headers=developer, json=run_body).json() == run.json()
    assert client.post(path, headers=reviewer, json=run_body).status_code == 403
    assert client.post("/v1/leads/not-a-uuid/runs", headers=developer,
                       json=run_body).status_code == 422
    queue_path = "/v1/workflows/actionable?limit=100"
    assert client.get(queue_path, headers=developer).status_code == 403
    run_id = run.json()["run_id"]
    assert run_id in {item["run_id"] for item in client.get(queue_path, headers=worker).json()}
    call = client.post(f"/v1/runs/{run_id}/tool-calls", headers=worker, json={
        "idempotency_key": f"queue-call-{marker}", "tool_id": tool.json()["tool_id"],
        "arguments": {"customer": "Fictional Buyer", "slot": run_body["slot"]},
    })
    assert call.status_code == 201, call.text
    assert run_id not in {item["run_id"] for item in client.get(queue_path, headers=worker).json()}
    approved = client.post(f"/v1/runs/{run_id}/tool-calls/{call.json()['tool_call_id']}/approve",
                           headers=reviewer, json={"valid_for_seconds": 300})
    assert approved.status_code == 200, approved.text
    assert run_id in {item["run_id"] for item in client.get(queue_path, headers=worker).json()}
    withdrawn = {**newer, "delivery_key": f"withdrawn-{marker}", "source_sequence": 4,
                 "lead": {**lead, "outreach_consent": False}}
    assert client.post(endpoint, headers=developer, json=withdrawn).status_code == 201
    blocked = {**run_body, "idempotency_key": f"blocked-{marker}"}
    assert client.post(path, headers=developer, json=blocked).status_code == 409
    with app.state.database.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM sentinel_runs WHERE idempotency_key=%s",
            (blocked["idempotency_key"],),
        ).fetchone()["n"] == 0
    assert client.post(path, headers=developer, json=run_body).json()["run_id"] == run_id
    print("PASS: atomic delivery replay, ordered updates, concurrent deduplication, roles, lead-run launch, and rollback.")


if __name__ == "__main__":
    main()
