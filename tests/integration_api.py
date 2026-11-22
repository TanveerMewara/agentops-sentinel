"""End-to-end API verification against project-local PostgreSQL."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres
from sentinel.database import Database
from sentinel.embeddings import EmbeddingService
from sentinel.properties import search_properties
from sentinel.provider_registry import CredentialCipher
from sentinel.runs import claim_tool_call
from sentinel.schemas import PropertyEmbeddingBackfill, PropertySearch
from sentinel.security import Principal, digest_key
from sentinel.service import claim_for_execution


OPENER = build_opener(ProxyHandler({}))


class FakeEmbeddingClient:
    """Test-only topical vectors; no network request or semantic-quality claim."""

    def __init__(self, **kwargs):
        self.embeddings = self

    def create(self, *, model, input, dimensions, encoding_format):
        assert model == "text-embedding-3-small"
        assert dimensions == 512 and encoding_format == "float"
        data = []
        for index, text_value in enumerate(input):
            text_value = text_value.lower()
            values = [0.0] * 512
            if "pool" in text_value or "golf" in text_value:
                values[0] = 1.0
            if "garden" in text_value:
                values[1] = 1.0
            if "metro" in text_value or "transit" in text_value:
                values[2] = 1.0
            if not any(values):
                values[3] = 1.0
            data.append(SimpleNamespace(index=index, embedding=values))
        return SimpleNamespace(
            data=data, usage=SimpleNamespace(total_tokens=len(input) * 12)
        )


def request(base, path, token=None, payload=None, *, method=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Key"] = token
    req = Request(base + path, data=data, headers=headers,
                  method=method or ("GET" if payload is None else "POST"))
    try:
        with OPENER.open(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        try:
            body = json.load(error)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Starlette emits a plain-text body when an unhandled exception
            # prevents the normal JSON error boundary from responding. Keep
            # the status observable without echoing potentially sensitive
            # response content into release logs.
            body = {"detail": "non_json_error"}
        return error.code, body


def free_port():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return reservation.getsockname()[1]


def wait_ready(base, process):
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError("Test service exited during startup.")
        try:
            if request(base, "/health")[0] == 200:
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Test service did not become ready.")


def start(command, environment):
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return process


def stop(process):
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def main():
    dev.setup()
    config = dev.load_config()
    environment = dev.child_environment()
    booking_port, api_port = free_port(), free_port()
    booking_base, api_base = f"http://127.0.0.1:{booking_port}", f"http://127.0.0.1:{api_port}"
    environment["SENTINEL_BOOKING_SERVICE_URL"] = booking_base
    environment["SENTINEL_API_URL"] = api_base
    database = Database(native_postgres.dsn())
    other_org_id, other_key_id = uuid4(), uuid4()
    other_token = f"snt_{uuid4().hex[:12]}_isolated-test-secret"
    other_prefix = "_".join(other_token.split("_", 2)[:2])
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sentinel_organizations (organization_id, name) VALUES (%s, %s)",
            (other_org_id, "Isolated integration tenant"),
        )
        connection.execute(
            """INSERT INTO sentinel_api_keys
               (api_key_id, organization_id, key_prefix, key_digest, label, role)
               VALUES (%s, %s, %s, %s, %s, 'developer')""",
            (other_key_id, other_org_id, other_prefix,
             digest_key(other_token, config["auth_pepper"]), "Isolation test"),
        )
    booking = start([sys.executable, "-m", "uvicorn", "lessons.booking_api_persistent:app",
                     "--host", "127.0.0.1", "--port", str(booking_port), "--log-level", "error"], environment)
    api = start([sys.executable, "-m", "uvicorn", "sentinel.asgi:app", "--app-dir", "src",
                 "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "error"], environment)
    try:
        wait_ready(booking_base, booking)
        wait_ready(api_base, api)
        keys = config["keys"]
        provider_body = {
            "model_alias": "openai_test_" + uuid4().hex[:8],
            "model_id": "configured-test-model",
            "api_key": "sk-integration-secret-that-must-stay-encrypted",
        }
        assert request(
            api_base, "/v1/model-providers/openai", keys["developer"], provider_body
        )[0] == 403
        code, provider = request(
            api_base, "/v1/model-providers/openai", keys["admin"], provider_body
        )
        assert code == 201 and provider["key_hint"].endswith("pted")
        assert "api_key" not in provider
        with database.connect() as connection:
            stored_credential = connection.execute(
                """SELECT encrypted_api_key FROM sentinel_model_provider_credentials
                   WHERE provider_id=%s""",
                (provider["provider_id"],),
            ).fetchone()["encrypted_api_key"]
        assert b"sk-integration-secret" not in bytes(stored_credential)
        code, providers = request(api_base, "/v1/model-providers", keys["developer"])
        assert code == 200 and any(
            item["provider_id"] == provider["provider_id"] for item in providers
        )
        property_prefix = uuid4().hex[:8]
        test_city = f"Gurugram {property_prefix}"
        qualified_lead_body = {
            "external_key": f"{property_prefix}-buyer",
            "channel": "manual", "customer_name": "Lead Riya",
            "contact_email": "riya@example.test", "city": test_city,
            "max_budget_inr": "15000000.00", "min_bedrooms": 2,
            "timeline": "within_month", "outreach_consent": True,
        }
        assert request(api_base, "/v1/leads", keys["reviewer"],
                       qualified_lead_body)[0] == 403
        code, lead_outcome = request(
            api_base, "/v1/leads", keys["developer"], qualified_lead_body
        )
        assert code == 201 and lead_outcome["outcome"] == "created"
        qualified_lead_id = lead_outcome["lead"]["lead_id"]
        assert lead_outcome["lead"]["qualification_status"] == "qualified"
        code, replayed_lead = request(
            api_base, "/v1/leads", keys["developer"], qualified_lead_body
        )
        assert code == 200 and replayed_lead["outcome"] == "unchanged"
        assert replayed_lead["lead"]["current_version"] == 1
        with database.connect() as connection:
            encrypted_lead = connection.execute(
                """SELECT encrypted_customer_name, encrypted_contact_email
                   FROM estate_leads WHERE lead_id=%s""",
                (qualified_lead_id,),
            ).fetchone()
        assert b"Lead Riya" not in bytes(encrypted_lead["encrypted_customer_name"])
        assert b"riya@example" not in bytes(encrypted_lead["encrypted_contact_email"])
        assert request(api_base, f"/v1/leads/{qualified_lead_id}",
                       other_token)[0] == 404
        assert request(api_base, f"/v1/leads/{qualified_lead_id}",
                       keys["worker"])[0] == 403
        assert request(api_base, f"/v1/leads/{qualified_lead_id}/events",
                       keys["developer"])[1][0]["event_type"] == "lead.created"
        incomplete_lead_body = {
            **qualified_lead_body, "external_key": f"{property_prefix}-incomplete",
            "contact_email": None, "outreach_consent": False,
        }
        code, incomplete_lead = request(
            api_base, "/v1/leads", keys["developer"], incomplete_lead_body
        )
        assert code == 201
        assert incomplete_lead["lead"]["qualification_status"] == "needs_information"
        properties = [
            {
                "external_key": f"{property_prefix}-golf",
                "title": "Luxury apartment with pool",
                "description": "Spacious home beside Golf Course Road with clubhouse.",
                "city": test_city, "locality": "Golf Course Road",
                "property_type": "apartment", "bedrooms": 3, "bathrooms": "2.5",
                "price_inr": "25000000.00", "area_sqft": "1800.00",
                "amenities": ["pool", "gym", "clubhouse"],
                "source_uri": f"https://estateflow.example/{property_prefix}/golf",
                "listing_status": "active",
            },
            {
                "external_key": f"{property_prefix}-villa",
                "title": "Garden villa",
                "description": "Quiet family villa with a private garden.",
                "city": "Jaipur", "locality": "Vaishali Nagar",
                "property_type": "villa", "bedrooms": 4, "bathrooms": "4.0",
                "price_inr": "18000000.00", "area_sqft": "2600.00",
                "amenities": ["garden", "parking"],
                "source_uri": f"https://estateflow.example/{property_prefix}/villa",
                "listing_status": "active",
            },
            {
                "external_key": f"{property_prefix}-metro",
                "title": "Modern metro apartment",
                "description": "Efficient apartment close to rapid metro and offices.",
                "city": test_city, "locality": "Sector 55",
                "property_type": "apartment", "bedrooms": 2, "bathrooms": "2.0",
                "price_inr": "12000000.00", "area_sqft": "1150.00",
                "amenities": ["gym", "parking"],
                "source_uri": f"https://estateflow.example/{property_prefix}/metro",
                "listing_status": "active",
            },
        ]
        code, ingested = request(
            api_base, "/v1/properties/batch", keys["developer"],
            {"properties": properties},
        )
        assert code == 200 and [item["outcome"] for item in ingested] == [
            "created", "created", "created",
        ]
        golf_id = ingested[0]["property"]["property_id"]
        code, unchanged = request(
            api_base, "/v1/properties", keys["developer"], properties[0]
        )
        assert code == 200 and unchanged["outcome"] == "unchanged"
        updated_golf = {**properties[0], "price_inr": "24500000.00"}
        code, updated = request(
            api_base, "/v1/properties", keys["developer"], updated_golf
        )
        assert code == 200 and updated["outcome"] == "updated"
        assert updated["property"]["current_version"] == 2
        with database.connect() as connection:
            version_count = connection.execute(
                "SELECT count(*) AS count FROM estate_property_versions WHERE property_id=%s",
                (golf_id,),
            ).fetchone()["count"]
        assert version_count == 2
        code, property_versions = request(
            api_base, f"/v1/properties/{golf_id}/versions", keys["developer"]
        )
        assert code == 200 and [item["version"] for item in property_versions] == [2, 1]
        search_body = {
            "query": "luxury pool golf", "city": test_city,
            "property_type": "apartment", "min_bedrooms": 3,
            "max_price_inr": "30000000.00", "required_amenities": ["pool"],
            "limit": 5,
        }
        assert request(
            api_base, "/v1/properties/search", keys["reviewer"], search_body
        )[0] == 403
        code, search = request(
            api_base, "/v1/properties/search", keys["developer"], search_body
        )
        assert code == 200 and search["strategy"] == "hybrid_lexical_v1"
        assert len(search["results"]) == 1
        assert search["results"][0]["property"]["property_id"] == golf_id
        evidence = search["results"][0]["evidence"]
        assert evidence["source_uri"] == updated_golf["source_uri"]
        assert evidence["property_version"] == 2 and "pool" in evidence["matched_terms"]
        code, stored_retrieval = request(
            api_base, f"/v1/property-searches/{search['retrieval_id']}", keys["developer"]
        )
        assert code == 200 and stored_retrieval["result_evidence"][0][
            "property_id"
        ] == golf_id
        assert request(
            api_base, f"/v1/property-searches/{search['retrieval_id']}", other_token
        )[0] == 404
        other_property_status, other_properties = request(
            api_base, "/v1/properties", other_token
        )
        assert other_property_status == 200, other_property_status
        assert other_properties == []
        assert request(api_base, f"/v1/properties/{golf_id}", other_token)[0] == 404

        embedding_alias = f"estate_embed_{property_prefix}"
        code, embedding_provider = request(
            api_base, "/v1/model-providers/openai", keys["admin"], {
                "model_alias": embedding_alias,
                "model_id": "text-embedding-3-small",
                "api_key": "sk-fake-embedding-key-for-integration-only",
            },
        )
        assert code == 201 and embedding_provider["model_alias"] == embedding_alias
        assert request(
            api_base, "/v1/properties/embeddings/backfill", keys["developer"],
            {"model_alias": embedding_alias, "external_key_prefix": property_prefix},
        )[0] == 403
        with database.connect() as connection:
            embedding_owner = connection.execute(
                """SELECT created_by_key_id, organization_id FROM estate_properties
                   WHERE property_id=%s""",
                (golf_id,),
            ).fetchone()
        embedding_principal = Principal(
            str(embedding_owner["created_by_key_id"]),
            str(embedding_owner["organization_id"]), "developer",
        )
        admin_token = keys["admin"]
        admin_prefix = "_".join(admin_token.split("_", 2)[:2])
        with database.connect() as connection:
            admin_row = connection.execute(
                """SELECT api_key_id, organization_id FROM sentinel_api_keys
                   WHERE key_prefix=%s AND key_digest=%s""",
                (admin_prefix, digest_key(admin_token, config["auth_pepper"])),
            ).fetchone()
        embedding_admin = Principal(
            str(admin_row["api_key_id"]), str(admin_row["organization_id"]),
            "admin",
        )
        embedding_service = EmbeddingService(
            database, CredentialCipher(config["credential_encryption_key"]),
            client_factory=FakeEmbeddingClient,
        )
        backfill_body = PropertyEmbeddingBackfill(
            model_alias=embedding_alias, external_key_prefix=property_prefix,
        )
        backfill = embedding_service.backfill(embedding_admin, backfill_body)
        assert backfill["embedded"] == 3 and backfill["remaining"] == 0
        assert embedding_service.backfill(
            embedding_admin, backfill_body
        )["embedded"] == 0
        vector_body = PropertySearch.model_validate({
            "query": "home near transit", "strategy": "vector",
            "embedding_model_alias": embedding_alias,
            "city": test_city, "property_type": "apartment", "limit": 5,
        })
        vector_search = embedding_service.search(embedding_principal, vector_body)
        assert vector_search["strategy"] == "vector_array_exact_v1"
        assert vector_search["results"][0]["property"]["external_key"] == (
            f"{property_prefix}-metro"
        )
        assert vector_search["results"][0]["evidence"]["embedding_id"]
        assert vector_search["results"][0]["evidence"]["property_version"] == 1
        code, vector_log = request(
            api_base, f"/v1/property-searches/{vector_search['retrieval_id']}",
            keys["developer"],
        )
        assert code == 200 and vector_log["embedding_backend"] == "postgres_array"
        assert vector_log["result_evidence"][0]["embedding_model_id"] == (
            "text-embedding-3-small"
        )
        assert request(
            api_base, f"/v1/property-searches/{vector_search['retrieval_id']}",
            other_token,
        )[0] == 404
        agent_body = {
            "slug": "estateflow_" + uuid4().hex[:8],
            "display_name": "EstateFlow Integration Agent",
            "description": "Exercises the organization-scoped registry.",
        }
        code, agent = request(api_base, "/v1/agents", keys["developer"], agent_body)
        assert code == 201 and agent["status"] == "active"
        agent_id = agent["agent_id"]
        code, agent_replay = request(api_base, "/v1/agents", keys["developer"], agent_body)
        assert code == 200 and agent_replay["agent_id"] == agent_id
        changed_agent = {**agent_body, "display_name": "Changed identity"}
        assert request(api_base, "/v1/agents", keys["developer"], changed_agent)[0] == 409
        assert request(api_base, "/v1/agents", keys["reviewer"], agent_body)[0] == 403

        object_schema = {
            "type": "object",
            "properties": {"customer": {"type": "string"}},
            "required": ["customer"],
            "additionalProperties": False,
        }
        tool_body = {
            "name": "book_viewing_" + uuid4().hex[:8],
            "version": "1.0.0",
            "description": "Creates a viewing through the guarded booking adapter.",
            "input_schema": object_schema,
            "output_schema": {
                "type": "object",
                "properties": {"booking_id": {"type": "string"}},
                "required": ["booking_id"],
                "additionalProperties": False,
            },
            "risk_level": "high",
            "approval_mode": "always",
        }
        code, tool = request(api_base, "/v1/tools", keys["developer"], tool_body)
        assert code == 201 and tool["risk_level"] == "high"
        tool_id = tool["tool_id"]
        code, tool_replay = request(api_base, "/v1/tools", keys["developer"], tool_body)
        assert code == 200 and tool_replay["tool_id"] == tool_id
        changed_tool = {**tool_body, "description": "A changed contract"}
        assert request(api_base, "/v1/tools", keys["developer"], changed_tool)[0] == 409
        unsafe_tool = {**tool_body, "name": "unsafe_" + uuid4().hex[:8], "approval_mode": "never"}
        assert request(api_base, "/v1/tools", keys["developer"], unsafe_tool)[0] == 422
        invalid_schema_tool = {
            **tool_body,
            "name": "invalid_schema_" + uuid4().hex[:8],
            "input_schema": {
                "type": "object", "properties": {"customer": {"type": "banana"}},
                "required": ["customer"], "additionalProperties": False,
            },
        }
        assert request(api_base, "/v1/tools", keys["developer"], invalid_schema_tool)[0] == 422

        grant_path = f"/v1/agents/{agent_id}/tools/{tool_id}"
        code, grant = request(
            api_base, grant_path, keys["developer"], {"max_calls_per_run": 2}
        )
        assert code == 200 and grant["max_calls_per_run"] == 2
        assert request(
            api_base, grant_path, keys["reviewer"], {"max_calls_per_run": 2}
        )[0] == 403
        code, grants = request(
            api_base, f"/v1/agents/{agent_id}/tools", keys["developer"]
        )
        assert code == 200 and len(grants) == 1 and grants[0]["tool_id"] == tool_id
        code, registry_events = request(
            api_base, "/v1/registry/events?limit=20", keys["developer"]
        )
        assert code == 200
        assert {event["event_type"] for event in registry_events} >= {
            "agent.registered", "tool.registered", "agent_tool_grant.created",
        }
        assert request(api_base, "/v1/agents", other_token)[1] == []
        assert request(api_base, "/v1/tools", other_token)[1] == []
        assert request(
            api_base, f"/v1/agents/{agent_id}/tools", other_token
        )[0] == 404

        version_body = {
            "version": "1.0.0",
            "instructions": "Help an operator arrange a property viewing safely.",
            "model_alias": "reasoning_primary",
            "max_steps": 3,
        }
        version_path = f"/v1/agents/{agent_id}/versions"
        code, agent_version = request(api_base, version_path, keys["developer"], version_body)
        assert code == 201 and agent_version["max_steps"] == 3
        version_id = agent_version["agent_version_id"]
        code, version_replay = request(api_base, version_path, keys["developer"], version_body)
        assert code == 200 and version_replay["agent_version_id"] == version_id
        assert request(
            api_base, version_path, keys["developer"],
            {**version_body, "instructions": "Changed immutable instructions."},
        )[0] == 409

        run_body = {
            "idempotency_key": "run-engine-" + uuid4().hex,
            "agent_version_id": version_id,
            "input": {"request": "Book a viewing for Asha"},
        }
        code, run = request(api_base, "/v1/runs", keys["developer"], run_body)
        assert code == 201 and run["status"] == "queued" and run["steps_used"] == 0
        run_id = run["run_id"]
        code, run_replay = request(api_base, "/v1/runs", keys["developer"], run_body)
        assert code == 200 and run_replay["run_id"] == run_id
        assert request(
            api_base, "/v1/runs", keys["developer"],
            {**run_body, "input": {"request": "Changed request"}},
        )[0] == 409

        # Changing the live grant cannot expand an already-created run's snapshot.
        code, updated_grant = request(
            api_base, grant_path, keys["developer"], {"max_calls_per_run": 5}
        )
        assert code == 200 and updated_grant["max_calls_per_run"] == 5
        invalid_call = {
            "idempotency_key": "invalid-call-" + uuid4().hex,
            "tool_id": tool_id,
            "arguments": {"customer": 42},
        }
        calls_path = f"/v1/runs/{run_id}/tool-calls"
        assert request(api_base, calls_path, keys["worker"], invalid_call)[0] == 422
        assert request(api_base, f"/v1/runs/{run_id}", keys["developer"])[1]["steps_used"] == 0
        first_call_body = {
            "idempotency_key": "tool-call-1-" + uuid4().hex,
            "tool_id": tool_id,
            "arguments": {"customer": "Asha"},
        }
        assert request(api_base, calls_path, keys["developer"], first_call_body)[0] == 403
        code, first_call = request(api_base, calls_path, keys["worker"], first_call_body)
        assert code == 201 and first_call["sequence"] == 1
        assert first_call["status"] == "awaiting_approval" and first_call["requires_approval"]
        code, first_replay = request(api_base, calls_path, keys["worker"], first_call_body)
        assert code == 200 and first_replay["tool_call_id"] == first_call["tool_call_id"]
        assert request(
            api_base, calls_path, keys["worker"],
            {**first_call_body, "arguments": {"customer": "Different"}},
        )[0] == 409
        first_approval_path = (
            f"/v1/runs/{run_id}/tool-calls/{first_call['tool_call_id']}/approve"
        )
        assert request(
            api_base, first_approval_path, keys["developer"], {"valid_for_seconds": 300}
        )[0] == 403
        assert request(
            api_base, first_approval_path, keys["reviewer"], {"valid_for_seconds": 300}
        )[1]["state"] == "approved"
        first_revoke_path = (
            f"/v1/runs/{run_id}/tool-calls/{first_call['tool_call_id']}/revoke"
        )
        assert request(api_base, first_revoke_path, keys["reviewer"], {})[1][
            "status"
        ] == "awaiting_approval"
        assert request(
            api_base, first_approval_path, keys["reviewer"], {"valid_for_seconds": 300}
        )[0] == 200
        unsupported_execute_path = (
            f"/v1/runs/{run_id}/tool-calls/{first_call['tool_call_id']}/execute"
        )
        assert request(api_base, unsupported_execute_path, keys["worker"], {})[0] == 501
        assert request(api_base, first_revoke_path, keys["reviewer"], {})[0] == 200
        first_reject_path = (
            f"/v1/runs/{run_id}/tool-calls/{first_call['tool_call_id']}/reject"
        )
        assert request(api_base, first_reject_path, keys["reviewer"], {})[1][
            "status"
        ] == "cancelled"

        second_call_body = {
            "idempotency_key": "tool-call-2-" + uuid4().hex,
            "tool_id": tool_id,
            "arguments": {"customer": "Ravi"},
        }
        code, second_call = request(api_base, calls_path, keys["worker"], second_call_body)
        assert code == 201 and second_call["sequence"] == 2
        second_reject_path = (
            f"/v1/runs/{run_id}/tool-calls/{second_call['tool_call_id']}/reject"
        )
        assert request(api_base, second_reject_path, keys["reviewer"], {})[1][
            "status"
        ] == "cancelled"
        third_old_call = {
            "idempotency_key": "tool-call-3-" + uuid4().hex,
            "tool_id": tool_id,
            "arguments": {"customer": "Meera"},
        }
        assert request(api_base, calls_path, keys["worker"], third_old_call)[0] == 409
        code, finished_run = request(
            api_base, f"/v1/runs/{run_id}/complete", keys["worker"], {}
        )
        assert code == 200 and finished_run["status"] == "succeeded"
        assert request(api_base, calls_path, keys["worker"], {
            **third_old_call, "idempotency_key": "terminal-" + uuid4().hex,
        })[0] == 409
        code, run_events = request(api_base, f"/v1/runs/{run_id}/events", keys["developer"])
        assert code == 200
        assert [event["event_type"] for event in run_events] == [
            "run.created", "tool_call.reserved", "tool_call.approved",
            "tool_call.approval_revoked", "tool_call.approved",
            "tool_call.approval_revoked", "tool_call.rejected",
            "tool_call.reserved", "tool_call.rejected", "run.succeeded",
        ]
        assert request(api_base, f"/v1/runs/{run_id}", other_token)[0] == 404

        # A later run sees the updated grant, while its max-step budget remains authoritative.
        next_run_body = {
            **run_body,
            "idempotency_key": "run-engine-next-" + uuid4().hex,
        }
        code, next_run = request(api_base, "/v1/runs", keys["developer"], next_run_body)
        assert code == 201
        next_calls_path = f"/v1/runs/{next_run['run_id']}/tool-calls"
        for number in range(1, 4):
            code, next_call = request(api_base, next_calls_path, keys["worker"], {
                "idempotency_key": f"next-tool-{number}-" + uuid4().hex,
                "tool_id": tool_id,
                "arguments": {"customer": f"Customer {number}"},
            })
            assert code == 201 and next_call["sequence"] == number
        assert request(api_base, next_calls_path, keys["worker"], {
            "idempotency_key": "step-limit-" + uuid4().hex,
            "tool_id": tool_id,
            "arguments": {"customer": "Over budget"},
        })[0] == 409

        executable_tool = {
            "name": "book_viewing",
            "version": "1.0.0",
            "description": "Creates one approved property viewing.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "minLength": 1},
                    "slot": {"type": "string", "minLength": 1},
                },
                "required": ["customer", "slot"],
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "properties": {"booking_id": {"type": "string", "minLength": 1}},
                "required": ["booking_id"],
                "additionalProperties": False,
            },
            "risk_level": "high",
            "approval_mode": "always",
        }
        code, dispatch_tool = request(
            api_base, "/v1/tools", keys["developer"], executable_tool
        )
        assert code in (200, 201)
        dispatch_tool_id = dispatch_tool["tool_id"]
        assert request(
            api_base, f"/v1/agents/{agent_id}/tools/{dispatch_tool_id}",
            keys["developer"], {"max_calls_per_run": 1},
        )[0] == 200
        dispatch_run_body = {
            "idempotency_key": "dispatch-run-" + uuid4().hex,
            "agent_version_id": version_id,
            "input": {"request": "Execute a reviewed booking"},
        }
        code, dispatch_run = request(
            api_base, "/v1/runs", keys["developer"], dispatch_run_body
        )
        assert code == 201
        dispatch_run_id = dispatch_run["run_id"]
        code, dispatch_call = request(
            api_base, f"/v1/runs/{dispatch_run_id}/tool-calls", keys["worker"], {
                "idempotency_key": "dispatch-call-" + uuid4().hex,
                "tool_id": dispatch_tool_id,
                "arguments": {
                    "customer": "Approved Asha",
                    "slot": "2030-02-01T10:00:00Z",
                },
            },
        )
        assert code == 201 and dispatch_call["status"] == "awaiting_approval"
        dispatch_call_id = dispatch_call["tool_call_id"]
        dispatch_execute_path = (
            f"/v1/runs/{dispatch_run_id}/tool-calls/{dispatch_call_id}/execute"
        )
        assert request(api_base, dispatch_execute_path, keys["worker"], {})[0] == 409
        assert request(
            api_base,
            f"/v1/runs/{dispatch_run_id}/tool-calls/{dispatch_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        code, dispatched = request(api_base, dispatch_execute_path, keys["worker"], {})
        assert code == 200 and dispatched["status"] == "completed"
        assert dispatched["result"]["booking_id"] == dispatched["external_id"]
        assert request(api_base, dispatch_execute_path, keys["worker"], {})[0] == 409
        assert request(
            api_base, f"/v1/runs/{dispatch_run_id}/complete", keys["worker"], {}
        )[1]["status"] == "succeeded"

        recovery_run_body = {
            **dispatch_run_body,
            "idempotency_key": "dispatch-recovery-" + uuid4().hex,
        }
        code, tool_recovery_run = request(
            api_base, "/v1/runs", keys["developer"], recovery_run_body
        )
        assert code == 201
        tool_recovery_run_id = tool_recovery_run["run_id"]
        recovery_arguments = {
            "customer": "Recovery Asha",
            "slot": "2030-02-02T10:00:00Z",
        }
        code, tool_recovery_call = request(
            api_base, f"/v1/runs/{tool_recovery_run_id}/tool-calls", keys["worker"], {
                "idempotency_key": "dispatch-recovery-call-" + uuid4().hex,
                "tool_id": dispatch_tool_id,
                "arguments": recovery_arguments,
            },
        )
        assert code == 201
        tool_recovery_call_id = tool_recovery_call["tool_call_id"]
        assert request(
            api_base,
            f"/v1/runs/{tool_recovery_run_id}/tool-calls/{tool_recovery_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        with database.connect() as connection:
            connection.execute(
                """UPDATE sentinel_tool_call_approvals
                   SET expires_at=now() - interval '1 second'
                   WHERE tool_call_id=%s AND state='approved'""",
                (tool_recovery_call_id,),
            )
        recovery_execute_path = (
            f"/v1/runs/{tool_recovery_run_id}/tool-calls/"
            f"{tool_recovery_call_id}/execute"
        )
        assert request(api_base, recovery_execute_path, keys["worker"], {})[0] == 409
        code, expired_calls = request(
            api_base, f"/v1/runs/{tool_recovery_run_id}/tool-calls", keys["developer"]
        )
        assert code == 200 and expired_calls[0]["status"] == "awaiting_approval"
        assert request(
            api_base,
            f"/v1/runs/{tool_recovery_run_id}/tool-calls/{tool_recovery_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        with database.connect() as connection:
            dispatch_worker_key = connection.execute(
                """SELECT api_key_id::text, organization_id::text
                   FROM sentinel_api_keys
                   WHERE organization_id=%s AND role='worker' AND revoked_at IS NULL""",
                (config["organization_id"],),
            ).fetchone()
        dispatch_worker_principal = Principal(
            dispatch_worker_key["api_key_id"], dispatch_worker_key["organization_id"], "worker"
        )
        claim_tool_call(
            database, dispatch_worker_principal, tool_recovery_run_id,
            tool_recovery_call_id, 30,
        )
        code, recovery_receipt = request(
            booking_base, "/operations", payload={
                "operation_id": tool_recovery_call_id,
                **recovery_arguments,
                "response_delay_seconds": 0,
            },
        )
        assert code == 200
        with database.connect() as connection:
            connection.execute(
                """UPDATE sentinel_tool_calls
                   SET lease_expires_at=now() - interval '1 second'
                   WHERE tool_call_id=%s""",
                (tool_recovery_call_id,),
            )
        assert request(
            api_base,
            f"/v1/runs/{tool_recovery_run_id}/tool-calls/"
            f"{tool_recovery_call_id}/reconcile",
            keys["worker"], {},
        )[0] == 200
        code, recovered_calls = request(
            api_base, f"/v1/runs/{tool_recovery_run_id}/tool-calls", keys["developer"]
        )
        assert code == 200 and recovered_calls[0]["status"] == "completed"
        assert recovered_calls[0]["external_id"] == recovery_receipt["booking_id"]
        code, tool_recovery_events = request(
            api_base, f"/v1/runs/{tool_recovery_run_id}/events", keys["developer"]
        )
        assert code == 200
        assert sum(
            event["event_type"] == "tool_call.execution_interrupted"
            for event in tool_recovery_events
        ) == 1
        assert sum(
            event["event_type"] == "tool_call.reconciliation_completed"
            for event in tool_recovery_events
        ) == 1

        workflow_version_body = {
            "version": "2.0.0",
            "instructions": "Arrange one requested viewing through Sentinel controls.",
            "model_alias": "deterministic_estateflow",
            "max_steps": 3,
        }
        code, workflow_version = request(
            api_base, version_path, keys["developer"], workflow_version_body
        )
        assert code in (200, 201)
        workflow_run_body = {
            "idempotency_key": "durable-workflow-" + uuid4().hex,
            "agent_version_id": workflow_version["agent_version_id"],
            "input": {
                "customer": "Workflow Asha",
                "slot": "2030-03-01T10:00:00Z",
                "property_query": search_body["query"],
                "property_filters": {
                    key: value for key, value in search_body.items() if key != "query"
                },
            },
        }
        code, workflow_run = request(
            api_base, "/v1/runs", keys["developer"], workflow_run_body
        )
        assert code == 201
        workflow_run_id = workflow_run["run_id"]
        workflow_start_path = f"/v1/runs/{workflow_run_id}/workflow/start"
        code, paused_workflow = request(
            api_base, workflow_start_path, keys["worker"], {}
        )
        assert code == 200 and paused_workflow["status"] == "waiting_approval"
        assert paused_workflow["retrieval_id"]
        assert len(paused_workflow["recommendations"]) == 1
        assert paused_workflow["recommendations"][0]["property"]["property_id"] == golf_id
        assert paused_workflow["recommendations"][0]["evidence"]["property_version"] == 2
        assert paused_workflow["recommendations"][0]["evidence"]["source_uri"] == updated_golf["source_uri"]
        workflow_call_id = paused_workflow["tool_call_id"]
        code, replayed_workflow = request(
            api_base, workflow_start_path, keys["worker"], {}
        )
        assert code == 200 and replayed_workflow["tool_call_id"] == workflow_call_id
        assert replayed_workflow["retrieval_id"] == paused_workflow["retrieval_id"]
        with database.connect() as connection:
            retrieval_count = connection.execute(
                "SELECT count(*) AS count FROM estate_retrieval_queries WHERE run_id=%s",
                (workflow_run_id,),
            ).fetchone()["count"]
        assert retrieval_count == 1

        # A listing can return to a prior value as a new immutable version. The
        # paused recommendation must still cite exactly what the reviewer saw.
        code, reverted = request(
            api_base, "/v1/properties", keys["developer"], properties[0]
        )
        assert code == 200 and reverted["property"]["current_version"] == 3
        with database.connect() as connection:
            property_owner = connection.execute(
                """SELECT created_by_key_id, organization_id FROM estate_properties
                   WHERE property_id=%s""",
                (golf_id,),
            ).fetchone()
        developer = Principal(
            str(property_owner["created_by_key_id"]),
            str(property_owner["organization_id"]), "developer",
        )
        retry_snapshot = search_properties(
            database, developer, PropertySearch.model_validate(search_body),
            run_id=workflow_run_id,
        )
        assert retry_snapshot["retrieval_id"] == paused_workflow["retrieval_id"]
        assert retry_snapshot["results"] == paused_workflow["recommendations"]

        # The old embedding stays in history but cannot represent version 3.
        stale_vector_body = PropertySearch.model_validate({
            "query": "pool near golf", "strategy": "vector",
            "embedding_model_alias": embedding_alias,
            "city": test_city, "property_type": "apartment",
            "min_bedrooms": 3, "required_amenities": ["pool"],
        })
        try:
            embedding_service.search(embedding_principal, stale_vector_body)
            raise AssertionError("Stale embedding was incorrectly used.")
        except HTTPException as error:
            assert error.status_code == 409
        assert embedding_service.backfill(
            embedding_admin, backfill_body
        )["embedded"] == 1
        refreshed_vector = embedding_service.search(
            embedding_principal, stale_vector_body
        )
        assert refreshed_vector["results"][0]["evidence"]["property_version"] == 3
        with database.connect() as connection:
            assert connection.execute(
                """SELECT count(*) AS count FROM estate_property_embeddings
                   WHERE property_id=%s AND model_alias=%s""",
                (golf_id, embedding_alias),
            ).fetchone()["count"] == 2

        # The in-process graph disappears here. Its PostgreSQL checkpoint must survive.
        stop(api)
        api = start(
            [sys.executable, "-m", "uvicorn", "sentinel.asgi:app", "--app-dir", "src",
             "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "error"],
            environment,
        )
        wait_ready(api_base, api)
        workflow_resume_path = f"/v1/runs/{workflow_run_id}/workflow/resume"
        assert request(api_base, workflow_resume_path, keys["worker"], {})[0] == 409
        assert request(
            api_base,
            f"/v1/runs/{workflow_run_id}/tool-calls/{workflow_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        code, completed_workflow = request(
            api_base, workflow_resume_path, keys["worker"], {}
        )
        assert code == 200 and completed_workflow["status"] == "completed"
        assert completed_workflow["result"]["booking_id"]
        assert completed_workflow["recommendations"] == paused_workflow["recommendations"]
        code, model_invocations = request(
            api_base, f"/v1/runs/{workflow_run_id}/model-invocations", keys["developer"]
        )
        assert code == 200 and len(model_invocations) == 1
        assert model_invocations[0]["provider"] == "deterministic"
        assert model_invocations[0]["status"] == "succeeded"
        code, persisted_workflow = request(
            api_base, workflow_start_path, keys["worker"], {}
        )
        assert code == 200 and persisted_workflow["status"] == "completed"
        assert persisted_workflow["tool_call_id"] == workflow_call_id
        assert persisted_workflow["retrieval_id"] == paused_workflow["retrieval_id"]

        no_match_body = {
            **workflow_run_body,
            "idempotency_key": "no-match-workflow-" + uuid4().hex,
            "input": {
                **workflow_run_body["input"],
                "property_query": "oceanfront impossible",
                "property_filters": {"city": test_city, "required_amenities": ["helipad"]},
            },
        }
        code, no_match_run = request(api_base, "/v1/runs", keys["developer"], no_match_body)
        assert code == 201
        no_match_path = f"/v1/runs/{no_match_run['run_id']}/workflow/start"
        code, no_match = request(api_base, no_match_path, keys["worker"], {})
        assert code == 200 and no_match["status"] == "no_match"
        assert no_match["retrieval_id"] and no_match["recommendations"] == []
        assert no_match["tool_call_id"] is None
        assert request(api_base, no_match_path, keys["worker"], {})[1] == no_match
        assert request(
            api_base, f"/v1/runs/{no_match_run['run_id']}", keys["developer"]
        )[1]["status"] == "cancelled"
        with database.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS count FROM estate_retrieval_queries WHERE run_id=%s",
                (no_match_run["run_id"],),
            ).fetchone()["count"] == 1

        rejected_workflow_body = {
            **workflow_run_body,
            "idempotency_key": "rejected-workflow-" + uuid4().hex,
        }
        code, rejected_run = request(
            api_base, "/v1/runs", keys["developer"], rejected_workflow_body
        )
        assert code == 201
        rejected_run_id = rejected_run["run_id"]
        code, rejected_pause = request(
            api_base, f"/v1/runs/{rejected_run_id}/workflow/start", keys["worker"], {}
        )
        assert code == 200 and rejected_pause["status"] == "waiting_approval"
        rejected_call_id = rejected_pause["tool_call_id"]
        assert request(
            api_base,
            f"/v1/runs/{rejected_run_id}/tool-calls/{rejected_call_id}/reject",
            keys["reviewer"], {},
        )[0] == 200
        code, rejected_workflow = request(
            api_base, f"/v1/runs/{rejected_run_id}/workflow/resume", keys["worker"], {}
        )
        assert code == 200 and rejected_workflow["status"] == "rejected"
        assert request(api_base, f"/v1/runs/{rejected_run_id}", keys["developer"])[1][
            "status"
        ] == "cancelled"

        property_tool_body = {**executable_tool, "version": "2.0.0",
            "input_schema": {**executable_tool["input_schema"],
                "properties": {**executable_tool["input_schema"]["properties"],
                    "property_id": {"type": "string", "format": "uuid"},
                    "property_version": {"type": "integer", "minimum": 1}},
                "required": ["customer", "slot", "property_id", "property_version"]}}
        code, property_tool = request(api_base, "/v1/tools", keys["developer"], property_tool_body)
        assert code in (200, 201)
        assert request(api_base, f"/v1/agents/{agent_id}/tools/{property_tool['tool_id']}",
                       keys["developer"], {"max_calls_per_run": 1})[0] == 200

        lead_run_body = {
            "idempotency_key": "lead-qualified-workflow-" + uuid4().hex,
            "agent_version_id": workflow_version["agent_version_id"],
            "input": {
                "lead_id": qualified_lead_id,
                "slot": "2030-04-01T10:00:00Z",
                "property_query": "metro",
                "property_filters": {"city": "Jaipur"},
            },
        }
        code, lead_run = request(api_base, "/v1/runs", keys["developer"],
                                 lead_run_body)
        assert code == 201
        lead_run_id = lead_run["run_id"]
        lead_start = f"/v1/runs/{lead_run_id}/workflow/start"
        code, lead_pause = request(api_base, lead_start, keys["worker"], {})
        assert code == 200 and lead_pause["status"] == "waiting_approval"
        assert lead_pause["lead_id"] == qualified_lead_id
        assert lead_pause["lead_version"] == 1
        assert len(lead_pause["recommendations"]) == 1
        assert lead_pause["recommendations"][0]["property"]["external_key"] == (
            f"{property_prefix}-metro"
        )
        lead_call_id = lead_pause["tool_call_id"]
        with database.connect() as connection:
            lead_call = connection.execute(
                "SELECT arguments FROM sentinel_tool_calls WHERE tool_call_id=%s",
                (lead_call_id,),
            ).fetchone()
        assert lead_call["arguments"]["customer"] == "Lead Riya"
        assert lead_call["arguments"]["property_id"] == lead_pause["recommendations"][0]["property"]["property_id"]
        assert lead_call["arguments"]["property_version"] == 1
        assert request(
            api_base, f"/v1/runs/{lead_run_id}/tool-calls/{lead_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        # A separate worker can finish the approved tool before the graph resumes.
        # Resumption must consume its saved receipt and still create CRM/draft state.
        code, recovered_lead_call = request(
            api_base, f"/v1/runs/{lead_run_id}/tool-calls/{lead_call_id}/execute",
            keys["worker"], {},
        )
        assert code == 200 and recovered_lead_call["status"] == "completed"
        code, lead_done = request(
            api_base, f"/v1/runs/{lead_run_id}/workflow/resume",
            keys["worker"], {},
        )
        assert code == 200 and lead_done["status"] == "completed"
        assert lead_done["result"] == recovered_lead_call["result"]
        assert lead_done["result"]["booking_id"]
        assert lead_done["crm_contact_id"] and lead_done["followup_draft_id"]
        code, crm_contacts = request(
            api_base, "/v1/crm/contacts", keys["developer"]
        )
        assert code == 200
        lead_contact = next(
            item for item in crm_contacts if item["lead_id"] == qualified_lead_id
        )
        assert lead_contact["stage"] == "viewing_booked"
        assert lead_contact["booking_id"] == lead_done["result"]["booking_id"]
        code, followups = request(
            api_base, "/v1/followups?status=draft", keys["developer"]
        )
        assert code == 200
        draft = next(item for item in followups
                     if item["draft_id"] == lead_done["followup_draft_id"])
        assert draft["recipient"] == "riya@example.test"
        assert lead_done["result"]["booking_id"] in draft["body"]
        assert request(
            api_base, f"/v1/followups/{draft['draft_id']}/approve",
            keys["developer"], {"expected_revision": draft["revision"]},
        )[0] == 403
        code, approved_draft = request(
            api_base, f"/v1/followups/{draft['draft_id']}/approve",
            keys["reviewer"], {"expected_revision": draft["revision"]},
        )
        assert code == 200 and approved_draft["status"] == "approved"
        assert request(
            api_base, f"/v1/followups/{draft['draft_id']}/approve",
            keys["reviewer"], {"expected_revision": draft["revision"]},
        )[1]["status"] == "approved"
        edit_body = {"expected_revision": draft["revision"],
                     "subject": "Your confirmed property viewing", "body": draft["body"]}
        edit_path = f"/v1/followups/{draft['draft_id']}"
        assert request(api_base, edit_path, keys["developer"], edit_body, method="PATCH")[0] == 403
        code, edited = request(api_base, edit_path, keys["reviewer"], edit_body, method="PATCH")
        assert code == 200 and edited["revision"] == 2 and edited["status"] == "draft"
        assert edited["approved_at"] is None
        assert request(api_base, edit_path, keys["reviewer"], edit_body, method="PATCH")[0] == 409
        assert request(api_base, edit_path + "/approve", keys["reviewer"],
                       {"expected_revision": 1})[0] == 409
        assert request(api_base, edit_path + "/approve", keys["reviewer"],
                       {"expected_revision": 2})[1]["status"] == "approved"
        code, outcomes = request(api_base, f"/v1/runs/{lead_run_id}/engagement", keys["developer"])
        assert code == 200 and outcomes["crm"]["status"] == "recorded"
        assert outcomes["followup"]["revision"] == 2 and outcomes["delivery"]["status"] == "not_sent"
        with database.connect() as connection:
            stored_draft = connection.execute(
                """SELECT encrypted_recipient, encrypted_subject, encrypted_body
                   FROM estate_followup_drafts WHERE draft_id=%s""",
                (draft["draft_id"],),
            ).fetchone()
        assert b"riya@example" not in bytes(stored_draft["encrypted_recipient"])
        assert b"Lead Riya" not in bytes(stored_draft["encrypted_body"])

        # Preserve a completed external action even if this separate lead is
        # routed to a human before graph resumption. No outreach draft is created.
        code, original_lead = request(api_base, f"/v1/leads/{qualified_lead_id}", keys["developer"])
        assert code == 200
        clone_body = {key: original_lead[key] for key in (
            "channel", "customer_name", "contact_email", "city", "max_budget_inr",
            "min_bedrooms", "timeline", "outreach_consent")}
        clone_body["external_key"] = "post-booking-change-" + uuid4().hex
        code, clone = request(api_base, "/v1/leads", keys["developer"], clone_body)
        assert code == 201
        clone_id = clone["lead"]["lead_id"]
        code, changed_run = request(api_base, "/v1/runs", keys["developer"], {
            **lead_run_body, "idempotency_key": "post-booking-run-" + uuid4().hex,
            "input": {**lead_run_body["input"], "lead_id": clone_id}})
        assert code == 201
        changed_run_id = changed_run["run_id"]
        code, changed_pause = request(api_base, f"/v1/runs/{changed_run_id}/workflow/start", keys["worker"], {})
        assert code == 200 and changed_pause["status"] == "waiting_approval"
        changed_call_path = f"/v1/runs/{changed_run_id}/tool-calls/{changed_pause['tool_call_id']}"
        assert request(api_base, changed_call_path + "/approve", keys["reviewer"], {"valid_for_seconds": 300})[0] == 200
        assert request(api_base, changed_call_path + "/execute", keys["worker"], {})[1]["status"] == "completed"
        assert request(api_base, f"/v1/leads/{clone_id}/handoff", keys["reviewer"], {"reason_code": "customer_requested"})[0] == 200
        code, changed_done = request(api_base, f"/v1/runs/{changed_run_id}/workflow/resume", keys["worker"], {})
        assert code == 200 and changed_done["status"] == "completed"
        assert changed_done["crm_contact_id"] and changed_done["followup_draft_id"] is None
        code, held = request(api_base, f"/v1/runs/{changed_run_id}/engagement", keys["developer"])
        assert code == 200 and held["review_required"] and held["followup"]["status"] == "blocked"
        assert held["tool_actions"][0]["status"] == "completed"

        unavailable_body = {**lead_run_body, "idempotency_key": "unavailable-property-" + uuid4().hex}
        code, unavailable_run = request(api_base, "/v1/runs", keys["developer"], unavailable_body)
        assert code == 201
        unavailable_id = unavailable_run["run_id"]
        code, unavailable_pause = request(api_base, f"/v1/runs/{unavailable_id}/workflow/start", keys["worker"], {})
        assert code == 200 and unavailable_pause["status"] == "waiting_approval"
        unavailable_call = unavailable_pause["tool_call_id"]
        unavailable_path = f"/v1/runs/{unavailable_id}/tool-calls/{unavailable_call}"
        assert request(api_base, unavailable_path + "/approve", keys["reviewer"], {"valid_for_seconds": 300})[0] == 200
        selected_id = unavailable_pause["recommendations"][0]["property"]["property_id"]
        try:
            with database.connect() as connection:
                connection.execute("UPDATE estate_properties SET listing_status='inactive' WHERE property_id=%s", (selected_id,))
            assert request(api_base, unavailable_path + "/execute", keys["worker"], {})[0] == 409
            code, unavailable_done = request(api_base, f"/v1/runs/{unavailable_id}/workflow/resume", keys["worker"], {})
            assert code == 200 and unavailable_done["status"] == "rejected"
            with database.connect() as connection:
                assert connection.execute("SELECT count(*) AS n FROM lesson_bookings WHERE operation_id=%s", (unavailable_call,)).fetchone()["n"] == 0
        finally:
            with database.connect() as connection:
                connection.execute("UPDATE estate_properties SET listing_status='active' WHERE property_id=%s", (selected_id,))

        blocked_body = {
            **lead_run_body,
            "idempotency_key": "lead-blocked-workflow-" + uuid4().hex,
            "input": {**lead_run_body["input"],
                      "lead_id": incomplete_lead["lead"]["lead_id"]},
        }
        code, blocked_run = request(api_base, "/v1/runs", keys["developer"],
                                    blocked_body)
        assert code == 201
        code, blocked_flow = request(
            api_base, f"/v1/runs/{blocked_run['run_id']}/workflow/start",
            keys["worker"], {},
        )
        assert code == 200 and blocked_flow["status"] == "lead_not_ready"
        assert blocked_flow["tool_call_id"] is None
        assert blocked_flow["retrieval_id"] is None

        handoff_body = {
            **lead_run_body,
            "idempotency_key": "lead-handoff-workflow-" + uuid4().hex,
        }
        code, handoff_run = request(api_base, "/v1/runs", keys["developer"],
                                    handoff_body)
        assert code == 201
        handoff_run_id = handoff_run["run_id"]
        code, handoff_pause = request(
            api_base, f"/v1/runs/{handoff_run_id}/workflow/start",
            keys["worker"], {},
        )
        assert code == 200 and handoff_pause["status"] == "waiting_approval"
        handoff_call_id = handoff_pause["tool_call_id"]
        handoff_approval_status, _ = request(
            api_base,
            f"/v1/runs/{handoff_run_id}/tool-calls/{handoff_call_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )
        assert handoff_approval_status == 200, handoff_approval_status
        handoff_path = f"/v1/leads/{qualified_lead_id}/handoff"
        code, routed_lead = request(
            api_base, handoff_path, keys["reviewer"],
            {"reason_code": "customer_requested"},
        )
        assert code == 200 and routed_lead["qualification_status"] == "human_review"
        assert routed_lead["current_version"] == 2
        assert request(
            api_base, handoff_path, keys["reviewer"],
            {"reason_code": "customer_requested"},
        )[1]["current_version"] == 2
        code, halted_flow = request(
            api_base, f"/v1/runs/{handoff_run_id}/workflow/resume",
            keys["worker"], {},
        )
        assert code == 200 and halted_flow["status"] == "lead_not_ready"
        assert request(
            api_base,
            f"/v1/runs/{handoff_run_id}/tool-calls/{handoff_call_id}/execute",
            keys["worker"], {},
        )[0] == 409
        with database.connect() as connection:
            cancelled_call = connection.execute(
                "SELECT status FROM sentinel_tool_calls WHERE tool_call_id=%s",
                (handoff_call_id,),
            ).fetchone()
        assert cancelled_call["status"] == "cancelled"
        assert request(api_base, "/v1/leads?status=human_review",
                       keys["reviewer"])[1][0]["lead_id"] == qualified_lead_id
        code, versions = request(
            api_base, f"/v1/leads/{qualified_lead_id}/versions",
            keys["reviewer"],
        )
        assert code == 200 and [item["version"] for item in versions] == [2, 1]
        assert "customer_name" not in versions[0]["requirements"]
        assert "contact_email" not in versions[0]["requirements"]
        assert request(
            api_base, f"/v1/leads/{qualified_lead_id}/resolve-review",
            keys["developer"], {"resolution_code": "answered_questions"},
        )[0] == 403
        code, resolved_lead = request(
            api_base, f"/v1/leads/{qualified_lead_id}/resolve-review",
            keys["reviewer"], {"resolution_code": "answered_questions"},
        )
        assert code == 200 and resolved_lead["qualification_status"] == "qualified"
        assert resolved_lead["current_version"] == 3
        assert request(
            api_base, f"/v1/leads/{qualified_lead_id}/resolve-review",
            keys["reviewer"], {"resolution_code": "answered_questions"},
        )[0] == 409
        assert request(
            api_base, f"/v1/runs/{handoff_run_id}/workflow/start",
            keys["worker"], {},
        )[1]["status"] == "lead_not_ready"

        identity = "integration-" + uuid4().hex
        body = {"idempotency_key": identity, "action_type": "book_viewing",
                "action": {"customer": "Integration Asha", "slot": "2030-01-15T10:00:00Z"}}
        code, operation = request(api_base, "/v1/operations", keys["developer"], body)
        assert code == 201 and operation["status"] == "awaiting_approval"
        operation_id = operation["operation_id"]

        code, replay = request(api_base, "/v1/operations", keys["developer"], body)
        assert code == 200 and replay["operation_id"] == operation_id
        changed = {**body, "action": {**body["action"], "slot": "2030-01-15T11:00:00Z"}}
        assert request(api_base, "/v1/operations", keys["developer"], changed)[0] == 409
        assert request(api_base, f"/v1/operations/{operation_id}/approve",
                       keys["developer"], {"valid_for_seconds": 300})[0] == 403
        code, approval = request(api_base, f"/v1/operations/{operation_id}/approve",
                                 keys["reviewer"], {"valid_for_seconds": 300})
        assert code == 200 and approval["state"] == "approved"
        assert request(api_base, f"/v1/operations/{operation_id}/execute",
                       keys["developer"], {})[0] == 403
        assert request(
            api_base, f"/v1/operations/{operation_id}/execute", keys["worker"], {}
        )[0] == 200
        code, executed = request(api_base, f"/v1/operations/{operation_id}", keys["developer"])
        assert code == 200 and executed["status"] == "succeeded" and executed["external_id"]
        assert request(api_base, f"/v1/operations/{operation_id}/execute",
                       keys["worker"], {})[0] == 409
        code, events = request(api_base, f"/v1/operations/{operation_id}/events", keys["developer"])
        assert code == 200
        assert [event["event_type"] for event in events] == [
            "operation.created", "approval.granted", "execution.started", "execution.succeeded"
        ]
        assert request(api_base, f"/v1/operations/{operation_id}", "bad-key")[0] == 401
        assert request(api_base, f"/v1/operations/{operation_id}", other_token)[0] == 404
        code, own_operations = request(api_base, "/v1/operations?limit=100", keys["developer"])
        assert code == 200 and any(item["operation_id"] == operation_id for item in own_operations)
        code, other_operations = request(api_base, "/v1/operations?limit=100", other_token)
        assert code == 200 and other_operations == []

        concurrent_body = {
            "idempotency_key": "concurrent-worker-" + uuid4().hex,
            "action_type": "book_viewing",
            "action": {"customer": "Concurrent Worker", "slot": "2030-01-16T10:00:00Z"},
        }
        code, concurrent_operation = request(
            api_base, "/v1/operations", keys["developer"], concurrent_body
        )
        assert code == 201
        concurrent_id = concurrent_operation["operation_id"]
        assert request(
            api_base, f"/v1/operations/{concurrent_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_codes = list(pool.map(
                lambda _: request(
                    api_base, f"/v1/operations/{concurrent_id}/execute",
                    keys["worker"], {},
                )[0],
                range(2),
            ))
        assert sorted(concurrent_codes) == [200, 409]
        code, concurrent_result = request(
            api_base, f"/v1/operations/{concurrent_id}", keys["developer"]
        )
        assert code == 200 and concurrent_result["status"] == "succeeded"
        code, concurrent_events = request(
            api_base, f"/v1/operations/{concurrent_id}/events", keys["developer"]
        )
        assert code == 200
        assert sum(event["event_type"] == "execution.started" for event in concurrent_events) == 1

        recovery_body = {
            "idempotency_key": "crashed-worker-" + uuid4().hex,
            "action_type": "book_viewing",
            "action": {"customer": "Recovery Worker", "slot": "2030-01-17T10:00:00Z"},
        }
        code, recovery_operation = request(
            api_base, "/v1/operations", keys["developer"], recovery_body
        )
        assert code == 201
        recovery_id = recovery_operation["operation_id"]
        assert request(
            api_base, f"/v1/operations/{recovery_id}/approve",
            keys["reviewer"], {"valid_for_seconds": 300},
        )[0] == 200
        with database.connect() as connection:
            worker_key = connection.execute(
                """SELECT api_key_id::text, organization_id::text
                   FROM sentinel_api_keys
                   WHERE organization_id=%s AND role='worker' AND revoked_at IS NULL""",
                (config["organization_id"],),
            ).fetchone()
        worker_principal = Principal(
            worker_key["api_key_id"], worker_key["organization_id"], "worker"
        )
        claim_for_execution(database, worker_principal, recovery_id)
        code, receipt = request(
            booking_base, "/operations", payload={
                "operation_id": recovery_id,
                **recovery_body["action"],
                "response_delay_seconds": 0,
            },
        )
        assert code == 200 and receipt["operation_id"] == recovery_id
        with database.connect() as connection:
            connection.execute(
                """UPDATE sentinel_operations
                   SET lease_expires_at=now() - interval '1 second'
                   WHERE operation_id=%s""",
                (recovery_id,),
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            recovery_codes = list(pool.map(
                lambda _: request(
                    api_base, f"/v1/operations/{recovery_id}/reconcile",
                    keys["worker"], {},
                )[0],
                range(2),
            ))
        assert sorted(recovery_codes) == [200, 409]
        code, recovered = request(
            api_base, f"/v1/operations/{recovery_id}", keys["developer"]
        )
        assert code == 200 and recovered["status"] == "succeeded"
        assert recovered["external_id"] == receipt["booking_id"]
        code, recovery_events = request(
            api_base, f"/v1/operations/{recovery_id}/events", keys["developer"]
        )
        assert code == 200
        assert sum(event["event_type"] == "execution.interrupted" for event in recovery_events) == 1
        assert sum(event["event_type"] == "reconciliation.succeeded" for event in recovery_events) == 1
        print("PASS: authenticated create, idempotent replay, exact approval, execution, and event history.")
        print("PASS: versioned agent/tool contracts, grants, risk policy, and registry isolation.")
        print("PASS: immutable agent versions, run snapshots, schema validation, and budgets.")
        print("PASS: exact tool-call approval, revocation, rejection, and safe adapter dispatch.")
        print("PASS: crashed tool-call execution recovered from evidence without replaying its write.")
        print("PASS: LangGraph approval interrupt survived API restart and resumed from PostgreSQL.")
        print("PASS: property-bound booking, unavailable-listing rejection, post-booking lead changes, and revision-specific draft review.")
        print("PASS: roles, changed payload, invalid key, duplicate execution, and tenant isolation were enforced.")
        print("PASS: two competing workers produced one claimed execution.")
        print("PASS: two recovery workers reconciled one expired execution without replaying its write.")
    finally:
        stop(api)
        stop(booking)
        with database.connect() as connection:
            connection.execute("DELETE FROM sentinel_api_keys WHERE api_key_id=%s", (other_key_id,))
            connection.execute("DELETE FROM sentinel_organizations WHERE organization_id=%s", (other_org_id,))


if __name__ == "__main__":
    main()
