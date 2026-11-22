"""Real MCP subprocess -> loopback HTTP API -> native PostgreSQL acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time
from uuid import uuid4

import uvicorn
from sentinel.client import SentinelClient
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.security import digest_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres


def message(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def main():
    dev.setup()
    config = dev.load_config()
    app = create_app(Settings(database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002", credential_encryption_key=config["credential_encryption_key"]))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    issued = None
    foreign_key_id = None
    admin = SentinelClient(base_url, config["keys"]["admin"])
    try:
        deadline = time.monotonic() + 90
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Local acceptance API did not start.")
            time.sleep(0.05)
        developer = SentinelClient(base_url, config["keys"]["developer"])
        worker = SentinelClient(base_url, config["keys"]["worker"])
        spec = importlib.util.spec_from_file_location("support_triage", ROOT / "examples" / "support_triage_agent.py")
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        marker = uuid4().hex
        result = example.integrate(developer, worker, idempotency_key="mcp_" + marker,
            topic="billing", severity="high", slug="mcp_" + marker)
        issued = admin.request("/v1/access/keys", {"label": "Synthetic MCP reviewer", "role": "reviewer"})
        environment = {**os.environ, "SENTINEL_API_URL": base_url, "SENTINEL_MCP_API_KEY": issued["token"]}
        initialize = message("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "native_acceptance", "version": "1"}})
        frames = [initialize, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                  message("tools/list", request_id=2),
                  message("tools/call", {"name": "sentinel_identity"}, 3),
                  message("tools/call", {"name": "sentinel_list_runs", "arguments": {"limit": 100}}, 4),
                  message("tools/call", {"name": "sentinel_run_timeline", "arguments": {"run_id": result["run_id"]}}, 5),
                  message("tools/call", {"name": "sentinel_run_timeline", "arguments": {"run_id": str(uuid4())}}, 6)]

        def run_bridge(frames):
            process = subprocess.run([sys.executable, "-m", "sentinel.mcp_stdio"],
                input="".join(json.dumps(frame) + "\n" for frame in frames),
                capture_output=True, text=True, env=environment, cwd=ROOT, timeout=90)
            assert process.returncode == 0, "MCP bridge failed."
            assert issued["token"] not in process.stdout + process.stderr
            assert environment["SENTINEL_MCP_API_KEY"] not in process.stdout + process.stderr
            return [json.loads(line) for line in process.stdout.splitlines()]

        replies = run_bridge(frames)
        assert len(replies) == 6
        assert replies[0]["result"]["protocolVersion"] == "2025-11-25"
        assert len(replies[1]["result"]["tools"]) == 3
        assert replies[2]["result"]["structuredContent"]["role"] == "reviewer"
        summaries = replies[3]["result"]["structuredContent"]["runs"]
        assert any(run["run_id"] == result["run_id"] for run in summaries)
        assert all(set(run) <= {"run_id", "agent_version_id", "status", "steps_used", "max_steps", "created_at", "started_at", "completed_at"} for run in summaries)
        timeline = replies[4]["result"]["structuredContent"]
        assert timeline["run"]["status"] == "succeeded" and timeline["metrics"]["model_calls"] == 0
        assert "classification" not in json.dumps(timeline)
        assert replies[5]["result"]["isError"] and "404" in replies[5]["result"]["content"][0]["text"]
        foreign_organization, foreign_key_id = uuid4(), uuid4()
        foreign_prefix = "snt_" + uuid4().hex
        foreign_token = foreign_prefix + "_" + uuid4().hex
        with app.state.database.connect() as connection:
            connection.execute("INSERT INTO sentinel_organizations(organization_id,name) VALUES (%s,%s)",
                               (foreign_organization, "Synthetic MCP isolation tenant"))
            connection.execute("""INSERT INTO sentinel_api_keys
                (api_key_id,organization_id,key_prefix,key_digest,label,role)
                VALUES (%s,%s,%s,%s,%s,'reviewer')""",
                (foreign_key_id, foreign_organization, foreign_prefix,
                 digest_key(foreign_token, config["auth_pepper"]), "Synthetic isolation key"))
        environment["SENTINEL_MCP_API_KEY"] = foreign_token
        isolated = run_bridge([initialize, frames[1], frames[4], frames[5]])
        assert isolated[1]["result"]["structuredContent"]["runs"] == []
        assert isolated[2]["result"]["isError"] and "404" in isolated[2]["result"]["content"][0]["text"]
        environment["SENTINEL_MCP_API_KEY"] = issued["token"]
        admin.request(f"/v1/access/keys/{issued['key']['api_key_id']}/revoke", {})
        denied = run_bridge([initialize, {"jsonrpc": "2.0", "method": "notifications/initialized"}, frames[3]])
        assert denied[0]["error"]["code"] == -32001
        assert denied[1]["error"]["code"] == -32000
        print("PASS: real MCP subprocess, API authentication, read-only discovery, safe summaries/timeline, missing-run denial, cross-tenant isolation, and revoked-key denial.")
    finally:
        if foreign_key_id:
            with app.state.database.connect() as connection:
                connection.execute("UPDATE sentinel_api_keys SET revoked_at=now() WHERE api_key_id=%s", (foreign_key_id,))
        if issued:
            try:
                admin.request(f"/v1/access/keys/{issued['key']['api_key_id']}/revoke", {})
            except Exception:
                pass
        server.should_exit = True
        thread.join(timeout=30)
        listener.close()


if __name__ == "__main__":
    main()
