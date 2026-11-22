"""Native PostgreSQL checks for key lifecycle and the independent agent client."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres
from sentinel.client import SentinelClient
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.security import digest_key


def main():
    dev.setup()
    config = dev.load_config()
    app = create_app(Settings(database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002", credential_encryption_key=config["credential_encryption_key"]))
    http = TestClient(app)
    admin = {"X-API-Key": config["keys"]["admin"]}
    developer = {"X-API-Key": config["keys"]["developer"]}
    worker = {"X-API-Key": config["keys"]["worker"]}
    path = "/v1/access/keys"
    body = {"label": "Synthetic reviewer", "role": "reviewer",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert http.get(path, headers=developer).status_code == 403
    assert http.post(path, headers=developer, json=body).status_code == 403
    created = http.post(path, headers=admin, json=body)
    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "no-store"
    issued = created.json()
    token, key_id = issued["token"], issued["key"]["api_key_id"]
    issued_headers = {"X-API-Key": token}
    assert http.get("/v1/me", headers=issued_headers).json()["role"] == "reviewer"
    assert http.get(path, headers=issued_headers).status_code == 403
    key_list = http.get(path, headers=admin)
    assert token not in key_list.text and "key_digest" not in key_list.text
    with app.state.database.connect() as connection:
        stored = connection.execute("SELECT key_digest FROM sentinel_api_keys WHERE api_key_id=%s", (key_id,)).fetchone()
        assert stored["key_digest"] == digest_key(token, config["auth_pepper"])
        connection.execute("UPDATE sentinel_api_keys SET expires_at=now()-interval '1 second' WHERE api_key_id=%s", (key_id,))
    assert http.get("/v1/me", headers=issued_headers).status_code == 401
    assert http.post(f"{path}/{key_id}/revoke", headers=admin, json={}).status_code == 200
    assert http.post(f"{path}/{key_id}/revoke", headers=admin, json={}).status_code == 200
    assert http.get("/v1/me", headers=issued_headers).status_code == 401
    audit = http.get("/v1/access/events?limit=100", headers=admin)
    assert token not in audit.text
    revocations = [event for event in audit.json() if event["target_key_id"] == key_id and event["event_type"] == "key.revoked"]
    assert len(revocations) == 1
    assert http.post(f"{path}/{uuid4()}/revoke", headers=admin, json={}).status_code == 404

    marker = uuid4().hex
    organization_id, fixture_key_id = uuid4(), uuid4()
    fixture_prefix = "snt_fixture" + marker
    fixture_token = fixture_prefix + "_" + uuid4().hex
    with app.state.database.connect() as connection:
        connection.execute("INSERT INTO sentinel_organizations(organization_id,name) VALUES (%s,%s)", (organization_id, "Synthetic access tenant"))
        connection.execute("INSERT INTO sentinel_api_keys(api_key_id,organization_id,key_prefix,key_digest,label,role) VALUES (%s,%s,%s,%s,%s,'admin')",
            (fixture_key_id, organization_id, fixture_prefix, digest_key(fixture_token, config["auth_pepper"]), "Synthetic administrator"))
    fixture_admin = {"X-API-Key": fixture_token}
    assert http.post(f"{path}/{fixture_key_id}/revoke", headers=admin, json={}).status_code == 404
    assert http.post(f"{path}/{fixture_key_id}/revoke", headers=fixture_admin, json={}).status_code == 409
    second = http.post(path, headers=fixture_admin, json={"label": "Second administrator", "role": "admin"}).json()
    second_headers = {"X-API-Key": second["token"]}
    def revoke_other(pair):
        header, target = pair
        return http.post(f"{path}/{target}/revoke", headers=header, json={})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(revoke_other, [(fixture_admin, second["key"]["api_key_id"]), (second_headers, str(fixture_key_id))]))
    assert sum(response.status_code == 200 for response in responses) == 1, [response.text for response in responses]
    assert all(response.status_code in (200, 401, 409) for response in responses)
    with app.state.database.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM sentinel_api_keys WHERE organization_id=%s AND role='admin' AND revoked_at IS NULL", (organization_id,)).fetchone()["n"] == 1

    class InProcessTransport:
        def open(self, request, timeout):
            parsed = urlsplit(request.full_url)
            response = http.request(request.get_method(), parsed.path + ("?" + parsed.query if parsed.query else ""),
                headers=dict(request.header_items()), content=request.data)
            if response.status_code >= 400:
                raise HTTPError(request.full_url, response.status_code, "API failure", {}, io.BytesIO(response.content))
            return io.BytesIO(response.content)
    sdk_developer = SentinelClient("http://localhost:8000", config["keys"]["developer"])
    sdk_worker = SentinelClient("http://localhost:8000", config["keys"]["worker"])
    sdk_developer.opener = sdk_worker.opener = InProcessTransport()
    spec = importlib.util.spec_from_file_location("support_triage", ROOT / "examples" / "support_triage_agent.py")
    agent_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent_module)
    arguments = {"idempotency_key": "support-fixture-" + marker, "topic": "billing", "severity": "high", "slug": "triage_" + marker}
    result = agent_module.integrate(sdk_developer, sdk_worker, **arguments)
    replay = agent_module.integrate(sdk_developer, sdk_worker, **arguments)
    assert result == replay and result["classification"] == {"queue": "billing", "priority": "urgent"}
    assert result["status"] == "succeeded"
    assert sdk_developer.timeline(result["run_id"])["metrics"]["model_calls"] == 0
    with app.state.database.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM sentinel_runs WHERE idempotency_key=%s", (arguments["idempotency_key"],)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM sentinel_tool_calls WHERE run_id=%s", (result["run_id"],)).fetchone()["n"] == 0
    print("PASS: one-time key issuance, digest-only storage, expiry, revocation replay, audit, tenant isolation, concurrent last-admin protection, and independent-agent client replay.")


if __name__ == "__main__":
    main()
