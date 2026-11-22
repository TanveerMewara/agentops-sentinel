"""Bounded OTLP/HTTP decoding and privacy-minimal telemetry persistence."""
from __future__ import annotations

from decimal import Decimal
import gzip
import hashlib
import json
import re
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest, ExportLogsServiceResponse
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest, ExportMetricsServiceResponse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest, ExportTraceServiceResponse

from .external_traces import validate_external_run
from .runs import add_run_event
from .security import require_roles

DECODED_LIMIT = 4 * 1024 * 1024
MAX_ITEMS = 10_000
CONTENT_TYPES = {'application/json', 'application/x-protobuf'}
SIGNALS = ('traces', 'metrics', 'logs')
_PRICING_KEY = re.compile(r'^[a-z][a-z0-9_.-]{2,63}$')


class TelemetryPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    retention_days: int = Field(ge=1, le=365)
    required_signals: list[Literal['traces', 'metrics', 'logs']] = Field(min_length=1, max_length=3)
    require_token_usage: bool = False
    require_cost: bool = False


class RateCardCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pricing_key: str = Field(pattern=r'^[a-z][a-z0-9_.-]{2,63}$')
    input_usd_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=8)
    output_usd_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=8)


def _decompress(body: bytes, encoding: str | None) -> bytes:
    normalized = (encoding or 'identity').strip().lower()
    if normalized in ('', 'identity'):
        decoded = body
    elif normalized == 'gzip':
        try:
            decoder = gzip.GzipFile(fileobj=__import__('io').BytesIO(body))
            decoded = decoder.read(DECODED_LIMIT + 1)
        except (gzip.BadGzipFile, EOFError, OSError):
            raise HTTPException(400, 'Invalid gzip OTLP body.') from None
    else:
        raise HTTPException(415, 'Only identity and gzip Content-Encoding are supported.')
    if len(decoded) > DECODED_LIMIT:
        raise HTTPException(413, 'Decoded OTLP request exceeds the 4 MiB limit.')
    return decoded


def _message_types(signal):
    return {
        'traces': (ExportTraceServiceRequest, ExportTraceServiceResponse),
        'metrics': (ExportMetricsServiceRequest, ExportMetricsServiceResponse),
        'logs': (ExportLogsServiceRequest, ExportLogsServiceResponse),
    }[signal]


def _trace_dict(message: ExportTraceServiceRequest) -> dict:
    resources = []
    for resource_spans in message.resource_spans:
        scopes = []
        for scope_spans in resource_spans.scope_spans:
            spans = []
            for span in scope_spans.spans:
                item = {
                    'traceId': span.trace_id.hex(), 'spanId': span.span_id.hex(),
                    'parentSpanId': span.parent_span_id.hex(), 'name': span.name,
                    'startTimeUnixNano': str(span.start_time_unix_nano),
                    'endTimeUnixNano': str(span.end_time_unix_nano),
                    'attributes': MessageToDict(span, preserving_proto_field_name=False,
                                                use_integers_for_enums=True).get('attributes', []),
                    'status': {'code': int(span.status.code)},
                }
                spans.append(item)
            scopes.append({'spans': spans})
        resources.append({'scopeSpans': scopes})
    return {'resourceSpans': resources}


def decode_otlp(signal: str, body: bytes, content_type: str | None,
                content_encoding: str | None) -> tuple[object, dict, bytes, str]:
    media_type = (content_type or '').split(';', 1)[0].strip().lower()
    if media_type not in CONTENT_TYPES:
        raise HTTPException(415, 'OTLP Content-Type must be application/json or application/x-protobuf.')
    decoded = _decompress(body, content_encoding)
    request_type, _ = _message_types(signal)
    message = request_type()
    try:
        if media_type == 'application/json':
            raw = json.loads(decoded.decode('utf-8'))
            if not isinstance(raw, dict):
                raise ValueError
        else:
            message.ParseFromString(decoded)
            raw = _trace_dict(message) if signal == 'traces' else MessageToDict(
                message, preserving_proto_field_name=False, use_integers_for_enums=True)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError, DecodeError):
        raise HTTPException(400, f'Invalid OTLP {signal} payload.') from None
    if signal == 'traces' and media_type == 'application/json':
        raw = json.loads(decoded.decode('utf-8'))
    return message, raw, decoded, media_type


def otlp_success(signal: str, media_type: str) -> tuple[bytes, str]:
    _, response_type = _message_types(signal)
    response = response_type()
    if media_type == 'application/x-protobuf':
        return response.SerializeToString(), media_type
    return b'{}', media_type


def _any_value(value):
    if not isinstance(value, dict):
        return None
    for key in ('stringValue', 'intValue', 'doubleValue', 'boolValue'):
        if key in value:
            return value[key]
    return None


def _attributes(items) -> dict:
    result = {}
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get('key'), str):
            result[item['key']] = _any_value(item.get('value'))
    return result


def _point_value(point):
    for key in ('asInt', 'asDouble'):
        if key in point and not isinstance(point[key], bool):
            return Decimal(str(point[key]))
    if 'sum' in point and not isinstance(point['sum'], bool):
        return Decimal(str(point['sum']))
    return None


def summarize_metrics(payload: dict) -> dict:
    count = 0; input_tokens = 0; output_tokens = 0
    duration = {key:{'count':0,'sum':Decimal('0'),'max':None}
                for key in ('model','tool','retrieval')}; priced = {}
    for resource in payload.get('resourceMetrics', []):
        for scope in resource.get('scopeMetrics', []):
            for metric in scope.get('metrics', []):
                name = metric.get('name', '')
                data = next((metric.get(k) for k in ('gauge','sum','histogram','exponentialHistogram','summary') if isinstance(metric.get(k), dict)), {})
                for point in data.get('dataPoints', []):
                    count += 1
                    if count > MAX_ITEMS: raise ValueError('Too many metric data points.')
                    value = _point_value(point)
                    if value is None or value < 0: continue
                    attrs = _attributes(point.get('attributes'))
                    if name in ('gen_ai.client.token.usage', 'gen_ai.server.token.usage'):
                        token_type = attrs.get('gen_ai.token.type')
                        amount = int(value)
                        if token_type == 'input': input_tokens += amount
                        elif token_type == 'output': output_tokens += amount
                        pricing_key = attrs.get('sentinel.pricing.key')
                        if isinstance(pricing_key, str) and _PRICING_KEY.fullmatch(pricing_key):
                            entry = priced.setdefault(pricing_key, {'input_tokens': 0, 'output_tokens': 0})
                            token_field = f'{token_type}_tokens'
                            if token_field in entry: entry[token_field] += amount
                    kind = ('model' if name in ('gen_ai.client.operation.duration','gen_ai.server.request.duration') else
                            'tool' if name == 'gen_ai.tool.call.duration' else
                            'retrieval' if name == 'gen_ai.retrieval.duration' else None)
                    if kind:
                        observations=int(point.get('count',1))
                        if observations < 0: raise ValueError
                        duration[kind]['count'] += observations
                        duration[kind]['sum'] += value
                        reported_max = point.get('max')
                        if reported_max is not None:
                            reported_max=Decimal(str(reported_max))
                            current=duration[kind]['max']
                            duration[kind]['max']=reported_max if current is None else max(current,reported_max)
                        elif observations == 1:
                            duration[kind]['max']=value if duration[kind]['max'] is None else max(duration[kind]['max'],value)
    return {'data_point_count': count, 'tokens': {'input': input_tokens, 'output': output_tokens},
            'priced_tokens': priced,
            'latency_ms': {key: {'count': value['count'], 'sum': round(float(value['sum'] * 1000), 3),
                'max': round(float(value['max'] * 1000),3) if value['max'] is not None else None}
                for key, value in duration.items()}}


def summarize_logs(payload: dict) -> dict:
    count = 0; levels = {'trace':0,'debug':0,'info':0,'warn':0,'error':0,'fatal':0,'unspecified':0}; correlated=set()
    for resource in payload.get('resourceLogs', []):
        for scope in resource.get('scopeLogs', []):
            for record in scope.get('logRecords', []):
                count += 1
                if count > MAX_ITEMS: raise ValueError('Too many log records.')
                severity = int(record.get('severityNumber', 0) or 0)
                label = ('trace' if severity <= 4 and severity else 'debug' if severity <= 8 and severity else
                         'info' if severity <= 12 and severity else 'warn' if severity <= 16 and severity else
                         'error' if severity <= 20 and severity else 'fatal' if severity else 'unspecified')
                levels[label] += 1
                trace_id = record.get('traceId')
                if isinstance(trace_id, str) and len(trace_id) in (24, 32): correlated.add(trace_id)
    return {'record_count': count, 'severity_counts': levels, 'correlated_trace_count': len(correlated),
            'content_stored': False}


def _policy(connection, organization_id, key_id=None):
    row = connection.execute('SELECT * FROM sentinel_telemetry_policies WHERE organization_id=%s', (organization_id,)).fetchone()
    if row: return row
    if key_id is None: return {'retention_days':30,'required_signals':['traces'],'require_token_usage':False,'require_cost':False}
    return connection.execute("""INSERT INTO sentinel_telemetry_policies
        (organization_id,updated_by_key_id) VALUES (%s,%s) RETURNING *""", (organization_id,key_id)).fetchone()


def ingest_signal(database, principal, run_id, signal, payload, decoded):
    require_roles('admin','developer','worker')(principal)
    try: summary = summarize_metrics(payload) if signal == 'metrics' else summarize_logs(payload)
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise HTTPException(422, f'OTLP {signal} limits or values are invalid.') from None
    content_hash = hashlib.sha256(decoded).hexdigest()
    with database.connect() as connection:
        validate_external_run(connection, principal.organization_id, run_id)
        policy = _policy(connection, principal.organization_id, principal.api_key_id)
        connection.execute('DELETE FROM sentinel_telemetry_batches WHERE organization_id=%s AND expires_at<=now()', (principal.organization_id,))
        existing = connection.execute("""SELECT * FROM sentinel_telemetry_batches
            WHERE run_id=%s AND organization_id=%s AND signal_type=%s AND content_hash=%s""",
            (run_id,principal.organization_id,signal,content_hash)).fetchone()
        if existing: return existing, False
        if signal == 'metrics':
            total = Decimal('0'); versions = {}
            for key, tokens in summary.pop('priced_tokens').items():
                rate = connection.execute("""SELECT * FROM sentinel_telemetry_rate_cards
                    WHERE organization_id=%s AND pricing_key=%s ORDER BY version DESC LIMIT 1""",
                    (principal.organization_id,key)).fetchone()
                if rate:
                    total += (Decimal(tokens['input_tokens']) * rate['input_usd_per_million'] +
                              Decimal(tokens['output_tokens']) * rate['output_usd_per_million']) / Decimal(1_000_000)
                    versions[key] = rate['version']
            summary['estimated_cost_usd'] = str(total.quantize(Decimal('0.00000001')))
            summary['priced_token_groups'] = len(versions); summary['rate_card_versions'] = versions
        row = connection.execute("""INSERT INTO sentinel_telemetry_batches
            (telemetry_batch_id,run_id,organization_id,signal_type,content_hash,summary,received_by_key_id,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,now()+(%s * interval '1 day')) RETURNING *""",
            (uuid4(),run_id,principal.organization_id,signal,content_hash,Jsonb(summary),principal.api_key_id,policy['retention_days'])).fetchone()
        add_run_event(connection,principal,run_id,f'telemetry.{signal}_received',
                      {'telemetry_batch_id':str(row['telemetry_batch_id']),'item_count':summary.get('data_point_count',summary.get('record_count',0))})
    return row, True


def set_policy(database, principal, body):
    require_roles('admin')(principal)
    required=list(dict.fromkeys(body.required_signals))
    if body.require_token_usage and 'metrics' not in required: raise HTTPException(422,'Token usage requires metrics in required_signals.')
    if body.require_cost and (not body.require_token_usage or 'metrics' not in required): raise HTTPException(422,'Cost requires metric token usage.')
    with database.connect() as connection:
        return connection.execute("""INSERT INTO sentinel_telemetry_policies
          (organization_id,retention_days,required_signals,require_token_usage,require_cost,updated_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id) DO UPDATE SET
          retention_days=excluded.retention_days,required_signals=excluded.required_signals,
          require_token_usage=excluded.require_token_usage,require_cost=excluded.require_cost,
          updated_by_key_id=excluded.updated_by_key_id,updated_at=now() RETURNING *""",
          (principal.organization_id,body.retention_days,required,body.require_token_usage,body.require_cost,principal.api_key_id)).fetchone()


def get_policy(database, principal):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection: return _policy(connection,principal.organization_id)


def create_rate_card(database, principal, body):
    require_roles('admin')(principal)
    with database.connect() as connection:
        connection.execute('SELECT 1 FROM sentinel_organizations WHERE organization_id=%s FOR UPDATE',
                           (principal.organization_id,)).fetchone()
        version=connection.execute('SELECT COALESCE(max(version),0)+1 AS version FROM sentinel_telemetry_rate_cards WHERE organization_id=%s AND pricing_key=%s',(principal.organization_id,body.pricing_key)).fetchone()['version']
        return connection.execute("""INSERT INTO sentinel_telemetry_rate_cards
          (rate_card_id,organization_id,pricing_key,version,input_usd_per_million,output_usd_per_million,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(uuid4(),principal.organization_id,body.pricing_key,version,body.input_usd_per_million,body.output_usd_per_million,principal.api_key_id)).fetchone()


def list_rate_cards(database, principal):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection:
        return connection.execute("""SELECT rate_card_id,pricing_key,version,
          input_usd_per_million,output_usd_per_million,created_at
          FROM sentinel_telemetry_rate_cards WHERE organization_id=%s
          ORDER BY pricing_key,version DESC""",(principal.organization_id,)).fetchall()


def telemetry_summary(database, principal, run_id):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection:
        validate_external_run(connection,principal.organization_id,run_id)
        policy=_policy(connection,principal.organization_id)
        batches=connection.execute('SELECT signal_type,summary,received_at,expires_at FROM sentinel_telemetry_batches WHERE run_id=%s AND organization_id=%s ORDER BY received_at',(run_id,principal.organization_id)).fetchall()
        trace=connection.execute('SELECT evidence,received_at,expires_at FROM sentinel_pending_otlp_traces WHERE run_id=%s AND organization_id=%s',(run_id,principal.organization_id)).fetchone()
        if trace is None:
            trace=connection.execute('SELECT evidence,created_at AS received_at,NULL AS expires_at FROM sentinel_external_traces WHERE run_id=%s AND organization_id=%s',(run_id,principal.organization_id)).fetchone()
    present=set(row['signal_type'] for row in batches)
    if trace: present.add('traces')
    metrics=[row['summary'] for row in batches if row['signal_type']=='metrics']
    tokens=sum(x.get('tokens',{}).get('input',0)+x.get('tokens',{}).get('output',0) for x in metrics)
    cost=sum((Decimal(x.get('estimated_cost_usd','0')) for x in metrics), Decimal('0'))
    priced_groups=sum(x.get('priced_token_groups',0) for x in metrics)
    latency={}
    for kind in ('model','tool','retrieval'):
        values=[x.get('latency_ms',{}).get(kind,{}) for x in metrics]
        maxima=[v.get('max') for v in values if v.get('max') is not None]
        latency[kind]={'count':sum(v.get('count',0) for v in values),
                       'sum':round(sum(v.get('sum',0) for v in values),3),
                       'max':round(max(maxima),3) if maxima else None}
    missing=sorted(set(policy['required_signals'])-present)
    gaps=[f'missing_{item}' for item in missing]
    if policy['require_token_usage'] and tokens==0: gaps.append('missing_token_usage')
    if policy['require_cost'] and priced_groups==0: gaps.append('missing_cost')
    return {'run_id':str(run_id),'trust':'caller_reported','complete':not gaps,'gaps':gaps,
            'policy':{'retention_days':policy['retention_days'],'required_signals':policy['required_signals'],
                      'require_token_usage':policy['require_token_usage'],'require_cost':policy['require_cost']},
            'signals':sorted(present),'batch_count':len(batches)+(1 if trace else 0),
            'tokens':{'total':tokens},'latency_ms':latency,
            'estimated_cost_usd':str(cost.quantize(Decimal('0.00000001'))),
            'privacy':{'raw_metrics_stored':False,'log_bodies_stored':False,'trace_content_attributes_stored':False}}


def purge_expired(database, principal):
    require_roles('admin')(principal)
    with database.connect() as connection:
        batches=connection.execute('DELETE FROM sentinel_telemetry_batches WHERE organization_id=%s AND expires_at<=now() RETURNING 1',(principal.organization_id,)).fetchall()
        pending=connection.execute('DELETE FROM sentinel_pending_otlp_traces WHERE organization_id=%s AND expires_at<=now() RETURNING 1',(principal.organization_id,)).fetchall()
    return {'deleted_batches':len(batches),'deleted_pending_traces':len(pending)}


def delete_run_telemetry(database, principal, run_id):
    require_roles('admin')(principal)
    with database.connect() as connection:
        validate_external_run(connection,principal.organization_id,run_id)
        batches=connection.execute('DELETE FROM sentinel_telemetry_batches WHERE run_id=%s AND organization_id=%s RETURNING 1',(run_id,principal.organization_id)).fetchall()
        pending=connection.execute('DELETE FROM sentinel_pending_otlp_traces WHERE run_id=%s AND organization_id=%s RETURNING 1',(run_id,principal.organization_id)).fetchall()
        add_run_event(connection,principal,run_id,'telemetry.deleted',{'batch_count':len(batches),'pending_trace_count':len(pending)})
    return {'deleted_batches':len(batches),'deleted_pending_traces':len(pending),
            'finalized_external_evidence_deleted':False}
