"""Native adapter failure/recovery, shared request limits and counter isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
from sentinel.adapters import AdapterRegistry
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.provider_circuit import ProviderCircuit
from sentinel.security import digest_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres


def main():
    dev.setup()
    config = dev.load_config()
    settings = Settings(database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002", credential_encryption_key=config["credential_encryption_key"])
    spec = importlib.util.spec_from_file_location("ticket_adapter", ROOT / "examples" / "support_ticket_adapter.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    with TemporaryDirectory(prefix="sentinel-adapter-") as directory:
        path = Path(directory) / "tickets.sqlite"
        adapter = example.SupportTicketAdapter(path)
        registry = AdapterRegistry()
        registry.install(example.CONTRACT, adapter)
        app = create_app(settings, adapters=registry)
        http = TestClient(app)
        headers = {role: {"X-API-Key": config["keys"][role]} for role in config["keys"]}

        def post(path, body, role="developer", statuses=(200, 201)):
            response = http.post(path, json=body, headers=headers[role])
            assert response.status_code in statuses, f"Unexpected status {response.status_code} at {path}."
            return response.json()

        marker = uuid4().hex
        agent = post("/v1/agents", {"slug": "tickets_" + marker, "display_name": "Sandbox ticket agent"})
        tool = post("/v1/tools", example.CONTRACT)
        grant_path = f"/v1/agents/{agent['agent_id']}/tools/{tool['tool_id']}"
        post(grant_path, {"max_calls_per_run": 2})
        changed_contract = deepcopy(example.CONTRACT)
        changed_contract["version"] = "9.0.0"
        unsupported = post("/v1/tools", changed_contract)
        post(f"/v1/agents/{agent['agent_id']}/tools/{unsupported['tool_id']}", {"max_calls_per_run": 1})
        version = post(f"/v1/agents/{agent['agent_id']}/versions", {"version": "1.0.0",
            "instructions": "Deterministic local ticket adapter check.", "model_alias": "deterministic_estateflow", "max_steps": 5})

        def reserve(key, tool_id):
            run = post("/v1/runs", {"agent_version_id": version["agent_version_id"],
                "idempotency_key": marker + key, "input": {"synthetic": True}})
            call = post(f"/v1/runs/{run['run_id']}/tool-calls", {"tool_id": tool_id,
                "idempotency_key": marker + key + "_call", "arguments": {"queue": "billing", "priority": "urgent"}}, "worker")
            base = f"/v1/runs/{run['run_id']}/tool-calls/{call['tool_call_id']}"
            return run, call, base

        run, call, base = reserve("success", tool["tool_id"])
        assert http.post(base + "/execute", json={}, headers=headers["worker"]).status_code == 409
        post(base + "/approve", {"valid_for_seconds": 300}, "reviewer")
        ready = http.get("/v1/tool-calls?status=authorized&limit=100", headers=headers["worker"])
        assert ready.status_code == 200 and any(item["tool_call_id"] == call["tool_call_id"] for item in ready.json())
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: http.post(base + "/execute", json={}, headers=headers["worker"]).status_code, range(2)))
        assert sorted(statuses) == [200, 409]
        post(f"/v1/runs/{run['run_id']}/complete", {}, "worker")

        adapter.lose_reply = True
        _, lost, lost_base = reserve("lost", tool["tool_id"])
        post(lost_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
        outcome = post(lost_base + "/execute", {}, "worker")
        assert outcome["status"] == "unknown"
        assert http.post(lost_base + "/execute", json={}, headers=headers["worker"]).status_code == 409
        recreated_registry = AdapterRegistry()
        recreated_registry.install(example.CONTRACT, example.SupportTicketAdapter(path))
        recreated_http = TestClient(create_app(settings, adapters=recreated_registry))
        recovered_response = recreated_http.post(lost_base + "/reconcile", json={}, headers=headers["worker"])
        assert recovered_response.status_code == 200
        recovered = recovered_response.json()
        assert recovered["status"] == "completed" and recovered["result"]["queue"] == "billing"
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT count(*) FROM receipts WHERE tool_call_id=?", (lost["tool_call_id"],)).fetchone()[0] == 1

        _, invalid, invalid_base = reserve("invalid_evidence", tool["tool_id"])
        post(invalid_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
        assert post(invalid_base + "/execute", {}, "worker")["status"] == "unknown"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE receipts SET arguments_hash='tampered' WHERE tool_call_id=?", (invalid["tool_call_id"],))
            connection.commit()
        assert post(invalid_base + "/reconcile", {}, "worker")["status"] == "needs_review"
        assert http.post(invalid_base + "/execute", json={}, headers=headers["worker"]).status_code == 409

        _, _, bad_base = reserve("unsupported", unsupported["tool_id"])
        post(bad_base + "/approve", {"valid_for_seconds": 300}, "reviewer")
        assert http.post(bad_base + "/execute", json={}, headers=headers["worker"]).status_code == 501

        issued = []
        foreign_key_id = None
        try:
            for _ in range(2):
                issued.append(post("/v1/access/keys", {"label": "Synthetic request-limit key", "role": "reviewer"}, "admin"))
            limited_settings = replace(settings, requests_per_window=5)
            replicas = [TestClient(create_app(limited_settings)), TestClient(create_app(limited_settings))]
            limited_headers = {"X-API-Key": issued[0]["token"]}
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(lambda index: replicas[index % 2].get("/v1/me", headers=limited_headers), range(20)))
            assert sum(response.status_code == 200 for response in responses) == 5
            assert sum(response.status_code == 429 for response in responses) == 15
            assert all(1 <= int(response.headers["retry-after"]) <= 60 and response.headers["cache-control"] == "no-store"
                       for response in responses if response.status_code == 429)
            with app.state.database.connect() as connection:
                stored = connection.execute("SELECT blocked_count FROM sentinel_request_limits WHERE api_key_id=%s", (issued[0]["key"]["api_key_id"],)).fetchone()
                assert stored["blocked_count"] == 15
                connection.execute("UPDATE sentinel_request_limits SET window_started_at=now()-interval '61 seconds' WHERE api_key_id=%s", (issued[0]["key"]["api_key_id"],))
            assert replicas[0].get("/v1/me", headers=limited_headers).status_code == 200
            assert replicas[1].get("/v1/me", headers={"X-API-Key": issued[1]["token"]}).status_code == 200

            overview = http.get("/v1/operations/overview", headers=headers["admin"])
            assert overview.status_code == 200
            assert overview.json()["access"]["rate_limit_blocks"] >= 15
            assert overview.json()["tool_calls"]["completed"] >= 2
            assert overview.json()["booking_circuit"] is None
            booking_app = create_app(settings)
            now = [0]
            circuit = ProviderCircuit(failure_threshold=1, cooldown_seconds=1, clock=lambda: now[0])
            booking_app.state.booking_adapter.circuit = circuit
            circuit.record_failure()
            booking_http = TestClient(booking_app)
            expected = {"state": "open", "retry_after_seconds": 1, "scope": "api_process"}
            for role in ("admin", "developer", "reviewer"):
                signal = booking_http.get("/v1/operations/overview", headers=headers[role])
                assert signal.status_code == 200 and signal.json()["booking_circuit"] == expected
                assert "127.0.0.1:8002" not in signal.text
            now[0] = 2
            signal = booking_http.get("/v1/operations/overview", headers=headers["admin"])
            assert signal.json()["booking_circuit"] == {**expected, "retry_after_seconds": 0}
            booking_http.close()
            assert all(key["token"] not in overview.text for key in issued)
            assert http.get("/v1/operations/overview", headers=headers["worker"]).status_code == 403
            foreign_organization, foreign_key_id = uuid4(), uuid4()
            prefix = "snt_" + uuid4().hex
            token = prefix + "_" + uuid4().hex
            with app.state.database.connect() as connection:
                connection.execute("INSERT INTO sentinel_organizations(organization_id,name) VALUES (%s,%s)", (foreign_organization, "Synthetic counter isolation tenant"))
                connection.execute("""INSERT INTO sentinel_api_keys(api_key_id,organization_id,key_prefix,key_digest,label,role)
                                      VALUES (%s,%s,%s,%s,%s,'reviewer')""", (foreign_key_id, foreign_organization, prefix, digest_key(token, config["auth_pepper"]), "Synthetic isolated key"))
            foreign_headers = {"X-API-Key": token}
            isolated = http.get("/v1/operations/overview", headers=foreign_headers).json()
            assert isolated["runs"] == {} and isolated["tool_calls"]["completed"] == 0
            assert isolated["access"]["active_keys"] == 1 and isolated["access"]["rate_limit_blocks"] == 0
            assert http.post(lost_base + "/reconcile", json={}, headers=foreign_headers).status_code == 403
        finally:
            for key in issued:
                post(f"/v1/access/keys/{key['key']['api_key_id']}/revoke", {}, "admin")
            if foreign_key_id:
                with app.state.database.connect() as connection:
                    connection.execute("UPDATE sentinel_api_keys SET revoked_at=now() WHERE api_key_id=%s", (foreign_key_id,))
        print("PASS: installed adapter contracts, approval, concurrent execution, lost-reply evidence-only recovery, shared replica rate limits, window reset, and isolated operational counters.")


if __name__ == "__main__":
    main()
