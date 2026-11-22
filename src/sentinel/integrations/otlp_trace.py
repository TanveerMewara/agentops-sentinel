"""Convert bounded OTLP/JSON trace exports into privacy-minimal Sentinel evidence."""
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ..external_traces import ExternalTraceCreate

_TRACE_ID = re.compile(r'^[0-9a-fA-F]{32}$')
_SPAN_ID = re.compile(r'^[0-9a-fA-F]{16}$')


class OTLPTraceCreate(BaseModel):
    """Authenticated server-side OTLP import request; output must be sanitized."""
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=8, max_length=200)
    trace_id: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{32}$')
    source: str = Field(default='opentelemetry', pattern=r'^[a-z][a-z0-9_-]{2,63}$')
    reported_status: Literal['succeeded', 'failed', 'cancelled', 'needs_review'] = 'succeeded'
    output: dict[str, JsonValue]
    otlp: dict[str, JsonValue]

    def evidence(self):
        return otlp_json_to_external_trace(self.otlp, self.output,
            trace_id=self.trace_id, source=self.source,
            reported_status=self.reported_status,
            idempotency_key=self.idempotency_key)


def _integer(value, label, *, maximum=None):
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        result = int(value)
    else:
        raise ValueError(f'{label} must be a nonnegative decimal integer.')
    if result < 0 or (maximum is not None and result > maximum):
        raise ValueError(f'{label} is outside the supported range.')
    return result


def _attributes(span):
    raw = span.get('attributes', [])
    if not isinstance(raw, list) or len(raw) > 256:
        raise ValueError('Each OTLP span may contain at most 256 attributes.')
    result = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str):
            raise ValueError('OTLP attributes must use key/value objects.')
        key = item['key']
        if key in result:
            raise ValueError('OTLP attribute keys must be unique within a span.')
        value = item.get('value')
        if not isinstance(value, dict):
            continue
        if 'stringValue' in value and isinstance(value['stringValue'], str):
            result[key] = value['stringValue']
        elif 'intValue' in value:
            try:
                result[key] = _integer(value['intValue'], 'OTLP integer attribute', maximum=10000000)
            except ValueError:
                pass
    return result


def _slug(value, fallback):
    text = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    return (text or fallback)[:60]


def _identity(attributes, raw_name):
    operation = str(attributes.get('gen_ai.operation.name', '')).lower()
    openinference = str(attributes.get('openinference.span.kind', '')).lower()
    tool_name = attributes.get('gen_ai.tool.name')
    if tool_name is not None or operation in ('execute_tool', 'tool') or openinference == 'tool':
        return 'tool', 'tool.' + _slug(tool_name or operation or raw_name, 'call')
    if operation in ('retrieval', 'retrieve') or openinference in ('retriever', 'retrieval'):
        return 'retrieval', 'retrieval.' + _slug(operation or raw_name, 'search')
    if operation and operation not in ('create_agent', 'invoke_agent', 'execute_agent'):
        return 'model', 'model.' + _slug(operation, 'generate')
    if openinference in ('llm', 'embedding'):
        return 'model', 'model.' + _slug(operation or openinference, 'generate')
    workflow = attributes.get('gen_ai.workflow.name')
    return 'agent', 'agent.' + _slug(workflow or raw_name, 'run')


def _flatten(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('resourceSpans'), list):
        raise ValueError('Expected an OTLP/JSON ExportTraceServiceRequest object.')
    spans = []
    for resource in payload['resourceSpans']:
        if not isinstance(resource, dict) or not isinstance(resource.get('scopeSpans'), list):
            raise ValueError('Each resourceSpans item needs a scopeSpans list.')
        for scope in resource['scopeSpans']:
            if not isinstance(scope, dict) or not isinstance(scope.get('spans'), list):
                raise ValueError('Each scopeSpans item needs a spans list.')
            spans.extend(scope['spans'])
            if len(spans) > 1000:
                raise ValueError('OTLP payload exceeds the 1000-span import scan limit.')
    if not spans or not all(isinstance(span, dict) for span in spans):
        raise ValueError('OTLP payload contains no valid span objects.')
    return spans


def select_otlp_trace_id(payload, trace_id=None):
    all_spans = _flatten(payload)
    ids = {span.get('traceId', '').lower() for span in all_spans
           if isinstance(span.get('traceId'), str) and _TRACE_ID.fullmatch(span['traceId'])}
    if trace_id is None:
        if len(ids) != 1:
            raise ValueError('Supply trace_id when an OTLP payload contains multiple traces.')
        return next(iter(ids))
    if not isinstance(trace_id, str) or not _TRACE_ID.fullmatch(trace_id):
        raise ValueError('trace_id must be 32 hexadecimal characters.')
    selected = trace_id.lower()
    if selected not in ids:
        raise ValueError('The selected trace_id is not present in the OTLP payload.')
    return selected


def otlp_json_to_external_trace(payload, output, *, trace_id=None,
                                source='opentelemetry', reported_status='succeeded',
                                idempotency_key=None):
    """Select one OTLP trace and return a validated Sentinel external-trace body."""
    all_spans = _flatten(payload)
    selected_trace = select_otlp_trace_id(payload, trace_id)
    selected = [span for span in all_spans
                if isinstance(span.get('traceId'), str) and span['traceId'].lower() == selected_trace]
    if len(selected) > 100:
        raise ValueError('A Sentinel external trace supports at most 100 spans.')

    parsed = []
    for span in selected:
        span_id = span.get('spanId')
        parent_id = span.get('parentSpanId') or None
        if not isinstance(span_id, str) or not _SPAN_ID.fullmatch(span_id):
            raise ValueError('Each selected OTLP span needs a 16-character hexadecimal spanId.')
        if parent_id is not None and (not isinstance(parent_id, str) or not _SPAN_ID.fullmatch(parent_id)):
            raise ValueError('OTLP parentSpanId must be empty or 16 hexadecimal characters.')
        start = _integer(span.get('startTimeUnixNano'), 'startTimeUnixNano')
        end = _integer(span.get('endTimeUnixNano'), 'endTimeUnixNano')
        if end < start:
            raise ValueError('OTLP span end time cannot precede its start time.')
        attributes = _attributes(span)
        kind, name = _identity(attributes, span.get('name'))
        status = span.get('status', {})
        failed = (isinstance(status, dict) and status.get('code') == 2) or bool(attributes.get('error.type'))
        input_tokens = output_tokens = None
        if kind == 'model':
            left = attributes.get('gen_ai.usage.input_tokens')
            right = attributes.get('gen_ai.usage.output_tokens')
            if type(left) is int and type(right) is int:
                input_tokens, output_tokens = left, right
        parsed.append({'span_id': span_id.lower(),
            'parent_id': parent_id.lower() if parent_id else None,
            'name': name, 'kind': kind, 'status': 'failed' if failed else 'completed',
            '_start': start, '_end': end, 'input_tokens': input_tokens,
            'output_tokens': output_tokens})

    by_id = {span['span_id']: span for span in parsed}
    if len(by_id) != len(parsed):
        raise ValueError('Selected OTLP span identifiers must be unique.')
    for span in parsed:
        seen = {span['span_id']}
        current = span
        while current['parent_id'] in by_id:
            parent = by_id[current['parent_id']]
            if parent['span_id'] in seen:
                raise ValueError('Selected OTLP parent references must be acyclic.')
            if current['_start'] < parent['_start'] or current['_end'] > parent['_end']:
                raise ValueError('An OTLP child span must fit inside its selected parent.')
            seen.add(parent['span_id'])
            current = parent

    minimum = min(span['_start'] for span in parsed)
    maximum = max(span['_end'] for span in parsed)
    duration_ms = (maximum - minimum + 999999) // 1000000
    if duration_ms > 86400000:
        raise ValueError('Selected OTLP trace exceeds the 24-hour evidence limit.')
    known_ids = {span['span_id'] for span in parsed}
    converted = []
    for span in parsed:
        start_ms = (span['_start'] - minimum) // 1000000
        end_ms = (span['_end'] - minimum + 999999) // 1000000
        converted.append({key: value for key, value in span.items() if not key.startswith('_')} | {
            'parent_id': span['parent_id'] if span['parent_id'] in known_ids else None,
            'start_offset_ms': start_ms, 'duration_ms': end_ms - start_ms})
    try:
        started_at = datetime.fromtimestamp(minimum / 1000000000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError('OTLP timestamp is outside the supported datetime range.') from None
    body = ExternalTraceCreate.model_validate({'schema_version': 1,
        'source': source, 'idempotency_key': idempotency_key or 'trace-' + uuid4().hex,
        'started_at': started_at, 'duration_ms': duration_ms,
        'reported_status': reported_status, 'spans': converted, 'output': output})
    return body.model_dump(mode='json')
