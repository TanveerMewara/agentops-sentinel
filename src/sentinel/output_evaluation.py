"""Bounded deterministic checks of caller-reported external JSON outputs."""
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .external_traces import canonical, read_trace_row

RULES = frozenset({'output_equals', 'output_schema'})
KEYWORDS = frozenset({'$schema', 'type', 'properties', 'required', 'additionalProperties',
    'items', 'enum', 'const', 'minLength', 'maxLength', 'minItems', 'maxItems',
    'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minProperties', 'maxProperties'})


def validate_definition(value, *, schema=False):
    try:
        if len(canonical(value)) > 16384:
            raise ValueError('Output rule exceeds 16 KiB.')
    except (RecursionError, ValueError):
        raise ValueError('Output rules must contain bounded finite JSON.') from None
    if not schema:
        return
    count = 0

    def walk(node, depth):
        nonlocal count
        count += 1
        if depth > 16 or count > 256:
            raise ValueError('Output schema exceeds structural limits.')
        if isinstance(node, bool):
            return
        if not isinstance(node, dict) or set(node) - KEYWORDS:
            raise ValueError('Unsupported output schema keyword.')
        if '$schema' in node and node['$schema'] != 'https://json-schema.org/draft/2020-12/schema':
            raise ValueError('Unsupported schema dialect.')
        properties = node.get('properties', {})
        if not isinstance(properties, dict):
            raise ValueError('Invalid schema properties.')
        for child in properties.values():
            walk(child, depth + 1)
        for name in ('items', 'additionalProperties'):
            if name in node:
                walk(node[name], depth + 1)

    walk(value, 0)
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError:
        raise ValueError('Invalid output schema.') from None


def json_equal(left, right):
    # JSON has one numeric family; Python's bool must not compare equal to int.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is bool and type(right) is bool and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


_UNSET = object()


def collect_facts(connection, organization_id, run_id, expected, *, row=_UNSET):
    if row is _UNSET:
        row = read_trace_row(connection, organization_id, run_id)
    facts = {'external_output_present': row is not None,
        'external_output_trust': 'caller_reported' if row else None,
        'external_trace_id': str(row['trace_id']) if row else None,
        'external_trace_hash': row['content_hash'] if row else None}
    for name in RULES:
        if expected.get(name) is None:
            continue
        if row is None:
            facts[name] = False
        elif name == 'output_equals':
            facts[name] = json_equal(row['evidence']['output'], expected[name])
        else:
            facts[name] = Draft202012Validator(expected[name]).is_valid(row['evidence']['output'])
    return facts
