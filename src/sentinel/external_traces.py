"""Immutable caller-reported evidence, separate from governed execution ledgers."""
import hashlib
import json
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from .runs import add_run_event, get_run
from .security import require_roles


class ExternalSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    span_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    parent_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    kind: Literal["agent", "model", "tool", "retrieval"]
    status: Literal["completed", "failed", "needs_review"]
    start_offset_ms: int = Field(ge=0, le=86400000, strict=True)
    duration_ms: int = Field(ge=0, le=86400000, strict=True)
    input_tokens: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, le=10000000, strict=True)

    @model_validator(mode="after")
    def usage(self):
        if (self.input_tokens is None) != (self.output_tokens is None):
            raise ValueError("Supply both token counts or neither.")
        if self.kind != "model" and self.input_tokens is not None:
            raise ValueError("Only model spans carry token counts.")
        return self


class ExternalTraceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=8, max_length=200)
    source: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    started_at: AwareDatetime
    duration_ms: int = Field(ge=0, le=86400000, strict=True)
    reported_status: Literal["succeeded", "failed", "cancelled", "needs_review"]
    spans: list[ExternalSpan] = Field(min_length=1, max_length=100)
    output: dict[str, JsonValue]

    @model_validator(mode="after")
    def bounded_tree(self):
        by_id = {span.span_id: span for span in self.spans}
        if len(by_id) != len(self.spans):
            raise ValueError("Span identifiers must be unique.")
        for span in self.spans:
            if span.start_offset_ms + span.duration_ms > self.duration_ms:
                raise ValueError("Span exceeds trace duration.")
            seen = {span.span_id}
            current = span
            while current.parent_id is not None:
                parent = by_id.get(current.parent_id)
                if parent is None or parent.span_id in seen:
                    raise ValueError("Parent references must form an acyclic tree.")
                if (current.start_offset_ms < parent.start_offset_ms or
                    current.start_offset_ms + current.duration_ms > parent.start_offset_ms + parent.duration_ms):
                    raise ValueError("A child span must fit inside its parent.")
                seen.add(parent.span_id)
                current = parent
        try:
            encoded = canonical(self.model_dump(mode="json"))
        except (ValueError, RecursionError):
            raise ValueError("Evidence must be finite JSON.") from None
        if len(encoded) > 65536:
            raise ValueError("Evidence exceeds the 64 KiB limit.")
        return self


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def read_trace_row(connection, organization_id, run_id):
    return connection.execute(
        'SELECT trace_id, content_hash, evidence FROM sentinel_external_traces WHERE run_id=%s AND organization_id=%s',
        (run_id, organization_id),
    ).fetchone()


def trace_view(row, *, include_output=False):
    evidence = row["evidence"]
    models = [span for span in evidence["spans"] if span["kind"] == "model"]
    known = [span for span in models if span["input_tokens"] is not None]
    result = {key: row[key] for key in ("trace_id", "run_id", "idempotency_key", "content_hash", "created_at")}
    result.update({"schema_version": 1, "source": evidence["source"],
        "started_at": evidence["started_at"], "reported_status": evidence["reported_status"],
        "duration_ms": evidence["duration_ms"], "spans": evidence["spans"],
        "trust": "caller_reported", "governed_execution_proof": False,
        "output_available": True, "output_included": include_output,
        "usage": {"model_spans": len(models), "spans_with_usage": len(known),
            "complete_for_reported_model_spans": len(known) == len(models),
            "reported_tokens": sum(span["input_tokens"] + span["output_tokens"] for span in known),
            "all_external_activity_captured": False}})
    if include_output:
        result["output"] = evidence["output"]
    return result


def ingest_trace(database, principal, run_id, body):
    require_roles("admin", "developer", "worker")(principal)
    evidence = body.model_dump(mode="json", exclude={"idempotency_key"})
    content_hash = hashlib.sha256(canonical(evidence)).hexdigest()
    with database.connect() as connection:
        validate_external_run(connection, principal.organization_id, run_id, for_update=True)
        existing = connection.execute(
            "SELECT * FROM sentinel_external_traces WHERE run_id=%s AND organization_id=%s",
            (run_id, principal.organization_id),
        ).fetchone()
        if existing:
            if existing["idempotency_key"] != body.idempotency_key or existing["content_hash"] != content_hash:
                raise HTTPException(409, "This run already has a different finalized external trace.")
            return trace_view(existing), False
        row = connection.execute(
            """INSERT INTO sentinel_external_traces
               (trace_id,run_id,organization_id,idempotency_key,evidence,content_hash,created_by_key_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (uuid4(),run_id,principal.organization_id,body.idempotency_key,Jsonb(evidence),content_hash,principal.api_key_id),
        ).fetchone()
        add_run_event(connection,principal,run_id,"external_trace.recorded",{
            "trace_id":str(row["trace_id"]),"span_count":len(body.spans),"trust":"caller_reported"})
    return trace_view(row), True


def validate_external_run(connection, organization_id, run_id, *, for_update=False):
    run = get_run(connection, organization_id, run_id, for_update=for_update)
    version = connection.execute(
        "SELECT model_alias FROM sentinel_agent_versions WHERE agent_version_id=%s AND organization_id=%s",
        (run["agent_version_id"], organization_id),
    ).fetchone()
    marker = run["input_payload"].get("workflow")
    if (marker == "estateflow" or
        (marker is not None and (not isinstance(marker, str) or not marker.strip())) or
        (marker is None and version["model_alias"] != "external_agent")):
        raise HTTPException(409, "External evidence requires an explicitly external run or external-agent alias.")
    return run


def read_trace(database, principal, run_id, include_output=False):
    require_roles("admin", "developer", "reviewer", "worker")(principal)
    with database.connect() as connection:
        get_run(connection, principal.organization_id, run_id)
        row = connection.execute(
            "SELECT * FROM sentinel_external_traces WHERE run_id=%s AND organization_id=%s",
            (run_id, principal.organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "External trace not found.")
    return trace_view(row, include_output=include_output)
