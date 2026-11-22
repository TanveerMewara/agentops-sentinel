import copy
import unittest

from pydantic import ValidationError

from sentinel.integrations.otlp_trace import otlp_json_to_external_trace


TRACE = '5b8efff798038103d269b633813fc60c'


def attribute(key, field, value):
    return {'key': key, 'value': {field: value}}


def span(span_id, name, start, end, *, parent='', attributes=None, status=None, trace_id=TRACE):
    result = {'traceId': trace_id, 'spanId': span_id, 'parentSpanId': parent,
        'name': name, 'startTimeUnixNano': str(start), 'endTimeUnixNano': str(end),
        'attributes': attributes or [], 'events': [{'name': 'PRIVATE-EVENT'}],
        'links': [{'attributes': [attribute('private', 'stringValue', 'PRIVATE-LINK')]}]}
    if status is not None:
        result['status'] = status
    return result


def payload(spans):
    return {'resourceSpans': [{'resource': {'attributes': [
        attribute('service.name', 'stringValue', 'PRIVATE-SERVICE')]},
        'scopeSpans': [{'scope': {'name': 'fixture'}, 'spans': spans}]}]}


class OTLPTraceTests(unittest.TestCase):
    def test_converts_semantic_spans_usage_hierarchy_status_and_omits_content(self):
        start = 1700000000000000000
        spans = [
            span('0000000000000001', 'Support Workflow', start, start + 9000000,
                attributes=[attribute('gen_ai.workflow.name', 'stringValue', 'Support Flow'),
                            attribute('gen_ai.input.messages', 'stringValue', 'PRIVATE-PROMPT')]),
            span('0000000000000002', 'chat private-model', start + 1000000, start + 4000000,
                parent='0000000000000001', attributes=[
                    attribute('gen_ai.operation.name', 'stringValue', 'chat'),
                    attribute('gen_ai.usage.input_tokens', 'intValue', '12'),
                    attribute('gen_ai.usage.output_tokens', 'intValue', '4'),
                    attribute('gen_ai.output.messages', 'stringValue', 'PRIVATE-RESPONSE')]),
            span('0000000000000003', 'tool', start + 5000000, start + 7000000,
                parent='0000000000000001', attributes=[
                    attribute('gen_ai.operation.name', 'stringValue', 'execute_tool'),
                    attribute('gen_ai.tool.name', 'stringValue', 'Send Reply'),
                    attribute('tool.arguments', 'stringValue', 'PRIVATE-ARGUMENT')],
                status={'code': 2, 'message': 'PRIVATE-ERROR'}),
            span('0000000000000004', 'retrieval customer-db', start + 7000000, start + 8000000,
                parent='0000000000000001', attributes=[
                    attribute('gen_ai.operation.name', 'stringValue', 'retrieval')])]
        evidence = otlp_json_to_external_trace(payload(spans), {'answer': 'sanitized'},
            idempotency_key='stable-otlp-trace')
        self.assertEqual([item['name'] for item in evidence['spans']],
            ['agent.support-flow', 'model.chat', 'tool.send-reply', 'retrieval.retrieval'])
        self.assertEqual((evidence['spans'][1]['input_tokens'],
                          evidence['spans'][1]['output_tokens']), (12, 4))
        self.assertEqual(evidence['spans'][2]['status'], 'failed')
        self.assertEqual(evidence['duration_ms'], 9)
        serialized = str(evidence)
        for secret in ('PRIVATE-PROMPT', 'PRIVATE-RESPONSE', 'PRIVATE-ARGUMENT',
                       'PRIVATE-ERROR', 'PRIVATE-EVENT', 'PRIVATE-LINK', 'PRIVATE-SERVICE',
                       'private-model'):
            self.assertNotIn(secret, serialized)

    def test_selects_one_trace_and_detaches_external_parent(self):
        start = 1700000000000000000
        other = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        body = payload([
            span('0000000000000001', 'first', start, start + 1),
            span('0000000000000002', 'second', start, start + 1,
                parent='ffffffffffffffff', trace_id=other)])
        with self.assertRaises(ValueError):
            otlp_json_to_external_trace(body, {})
        evidence = otlp_json_to_external_trace(body, {}, trace_id=other)
        self.assertEqual(len(evidence['spans']), 1)
        self.assertIsNone(evidence['spans'][0]['parent_id'])

    def test_rejects_invalid_ids_times_attributes_and_span_limits(self):
        start = 1700000000000000000
        valid = span('0000000000000001', 'run', start, start + 1)
        mutations = []
        bad = copy.deepcopy(valid); bad['spanId'] = 'bad'; mutations.append(payload([bad]))
        bad = copy.deepcopy(valid); bad['endTimeUnixNano'] = str(start - 1); mutations.append(payload([bad]))
        bad = copy.deepcopy(valid); bad['startTimeUnixNano'] = True; mutations.append(payload([bad]))
        bad = copy.deepcopy(valid); bad['attributes'] = [attribute('same','stringValue','a'), attribute('same','stringValue','b')]; mutations.append(payload([bad]))
        for body in mutations:
            with self.subTest(body=body), self.assertRaises(ValueError):
                otlp_json_to_external_trace(body, {})
        too_many = payload([span(f'{number:016x}', 'run', start, start + 1)
                            for number in range(1, 102)])
        with self.assertRaises(ValueError):
            otlp_json_to_external_trace(too_many, {})

    def test_validation_remains_strict_for_tree_output_source_and_status(self):
        start = 1700000000000000000
        child = span('0000000000000002', 'child', start, start + 20,
            parent='0000000000000001')
        parent = span('0000000000000001', 'parent', start + 10, start + 20)
        with self.assertRaises(ValueError):
            otlp_json_to_external_trace(payload([parent, child]), {})
        with self.assertRaises(ValidationError):
            otlp_json_to_external_trace(payload([span('0000000000000001','run',start,start+1)]),
                {'bad': object()})
        with self.assertRaises(ValidationError):
            otlp_json_to_external_trace(payload([span('0000000000000001','run',start,start+1)]),
                {}, source='UPPER', reported_status='invented')


if __name__ == '__main__':
    unittest.main()
