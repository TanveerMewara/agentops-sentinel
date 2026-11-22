"""Deterministic checks over bounded caller-reported external traces."""
from collections import Counter

from .external_traces import read_trace_row

RULES = frozenset({
    'required_trace_spans', 'ordered_trace_spans', 'forbidden_trace_spans',
    'external_reported_status', 'max_external_duration_ms',
    'max_reported_external_tokens', 'reported_model_usage_complete',
    'max_external_spans', 'max_failed_trace_spans',
})
_UNSET = object()


def _ordered(names, expected):
    position = 0
    for name in names:
        if position < len(expected) and name == expected[position]:
            position += 1
    return position == len(expected)


def collect_facts(connection, organization_id, run_id, expected, *, row=_UNSET):
    if row is _UNSET:
        row = read_trace_row(connection, organization_id, run_id)
    facts = {
        'external_trajectory_present': row is not None,
        'external_trajectory_trust': 'caller_reported' if row else None,
        'external_trajectory_trace_id': str(row['trace_id']) if row else None,
        'external_trajectory_trace_hash': row['content_hash'] if row else None,
    }
    active = {name for name in RULES if expected.get(name) is not None}
    if row is None:
        facts.update({name: False for name in active})
        facts.update({'reported_external_status': None, 'reported_external_duration_ms': None,
            'reported_external_span_count': None, 'reported_external_failed_spans': None,
            'reported_external_model_tokens': None,
            'reported_external_model_usage_complete': None})
        return facts

    evidence = row['evidence']
    spans = evidence['spans']
    parents = {span['span_id']: span.get('parent_id') for span in spans}

    def depth(span):
        value, seen = 0, set()
        parent = span.get('parent_id')
        while parent is not None and parent not in seen:
            seen.add(parent); value += 1; parent = parents.get(parent)
        return value

    ordered_spans = sorted(enumerate(spans), key=lambda item: (
        item[1]['start_offset_ms'], depth(item[1]), -item[1]['duration_ms'], item[0]))
    names = [span['name'] for _, span in ordered_spans]
    counts = Counter(names)
    models = [span for span in spans if span['kind'] == 'model']
    known = [span for span in models if span['input_tokens'] is not None]
    usage_complete = len(known) == len(models)
    tokens = sum(span['input_tokens'] + span['output_tokens'] for span in known)
    failed = sum(span['status'] in ('failed', 'needs_review') for span in spans)
    facts.update({'reported_external_status': evidence['reported_status'],
        'reported_external_duration_ms': evidence['duration_ms'],
        'reported_external_span_count': len(spans),
        'reported_external_failed_spans': failed,
        'reported_external_model_tokens': tokens,
        'reported_external_model_usage_complete': usage_complete})
    if 'required_trace_spans' in active:
        wanted = Counter(expected['required_trace_spans'])
        facts['required_trace_spans'] = all(counts[name] >= amount for name, amount in wanted.items())
    if 'ordered_trace_spans' in active:
        facts['ordered_trace_spans'] = _ordered(names, expected['ordered_trace_spans'])
    if 'forbidden_trace_spans' in active:
        facts['forbidden_trace_spans'] = not any(name in counts for name in expected['forbidden_trace_spans'])
    if 'external_reported_status' in active:
        facts['external_reported_status'] = evidence['reported_status'] == expected['external_reported_status']
    if 'max_external_duration_ms' in active:
        facts['max_external_duration_ms'] = evidence['duration_ms'] <= expected['max_external_duration_ms']
    if 'max_reported_external_tokens' in active:
        facts['max_reported_external_tokens'] = usage_complete and tokens <= expected['max_reported_external_tokens']
    if 'reported_model_usage_complete' in active:
        facts['reported_model_usage_complete'] = usage_complete is expected['reported_model_usage_complete']
    if 'max_external_spans' in active:
        facts['max_external_spans'] = len(spans) <= expected['max_external_spans']
    if 'max_failed_trace_spans' in active:
        facts['max_failed_trace_spans'] = failed <= expected['max_failed_trace_spans']
    return facts
