"""Authenticated OTLP/HTTP receipt followed by explicit output finalization."""
import hashlib
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .external_traces import ExternalTraceCreate, canonical, validate_external_run
from .integrations.otlp_trace import otlp_json_to_external_trace, select_otlp_trace_id
from .runs import add_run_event
from .security import require_roles


class OTLPFinalizeCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=8, max_length=200)
    reported_status: Literal['succeeded', 'failed', 'cancelled', 'needs_review']
    output: dict[str, JsonValue]


def receive_otlp(database, principal, run_id, payload, *, trace_id=None,
                 source='opentelemetry'):
    require_roles('admin', 'developer', 'worker')(principal)
    converted = otlp_json_to_external_trace(payload, {}, trace_id=trace_id,
        source=source, idempotency_key='pending-otlp-trace')
    selected = select_otlp_trace_id(payload, trace_id)
    evidence = {key: converted[key] for key in
        ('schema_version', 'source', 'started_at', 'duration_ms', 'spans')}
    content_hash = hashlib.sha256(canonical(evidence)).hexdigest()
    with database.connect() as connection:
        validate_external_run(connection, principal.organization_id, run_id, for_update=True)
        existing_final = connection.execute(
            'SELECT 1 FROM sentinel_external_traces WHERE run_id=%s AND organization_id=%s',
            (run_id, principal.organization_id)).fetchone()
        if existing_final:
            raise HTTPException(409, 'This run already has finalized external evidence.')
        existing = connection.execute(
            'SELECT * FROM sentinel_pending_otlp_traces WHERE run_id=%s AND organization_id=%s',
            (run_id, principal.organization_id)).fetchone()
        if existing:
            if (existing['selected_trace_id'] != selected or
                    existing['content_hash'] != content_hash):
                raise HTTPException(409, 'This run already has different pending OTLP evidence.')
            return existing, False
        policy = connection.execute('SELECT retention_days FROM sentinel_telemetry_policies WHERE organization_id=%s',
                                    (principal.organization_id,)).fetchone()
        retention_days = policy['retention_days'] if policy else 30
        row = connection.execute(
            """INSERT INTO sentinel_pending_otlp_traces
               (pending_trace_id,run_id,organization_id,selected_trace_id,evidence,
                content_hash,received_by_key_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (uuid4(), run_id, principal.organization_id, selected, Jsonb(evidence),
             content_hash, principal.api_key_id)).fetchone()
        connection.execute("UPDATE sentinel_pending_otlp_traces SET expires_at=now()+(%s * interval '1 day') WHERE pending_trace_id=%s",
                           (retention_days,row['pending_trace_id']))
        add_run_event(connection, principal, run_id, 'external_trace.otlp_received', {
            'pending_trace_id': str(row['pending_trace_id']),
            'span_count': len(evidence['spans']), 'trust': 'caller_reported'})
    return row, True


def finalize_otlp(database, principal, run_id, body):
    require_roles('admin', 'developer', 'worker')(principal)
    with database.connect() as connection:
        validate_external_run(connection, principal.organization_id, run_id)
        pending = connection.execute(
            'SELECT evidence FROM sentinel_pending_otlp_traces WHERE run_id=%s AND organization_id=%s',
            (run_id, principal.organization_id)).fetchone()
    if pending is None:
        raise HTTPException(404, 'Pending OTLP trace not found.')
    return ExternalTraceCreate.model_validate({**pending['evidence'],
        'idempotency_key': body.idempotency_key,
        'reported_status': body.reported_status, 'output': body.output})
