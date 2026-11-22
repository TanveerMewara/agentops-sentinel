import gzip
import json
import unittest

from fastapi import HTTPException
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

from sentinel.telemetry import decode_otlp, otlp_success, summarize_logs, summarize_metrics


def attr(key, field, value):
    return {'key':key,'value':{field:value}}


class TelemetryTests(unittest.TestCase):
    def test_json_gzip_metrics_tracks_usage_latency_and_pricing_without_attributes(self):
        payload={'resourceMetrics':[{'scopeMetrics':[{'metrics':[
            {'name':'gen_ai.client.token.usage','sum':{'dataPoints':[
                {'asInt':'12','attributes':[attr('gen_ai.token.type','stringValue','input'),
                    attr('sentinel.pricing.key','stringValue','model.standard'),
                    attr('private.prompt','stringValue','PRIVATE')]},
                {'asInt':'4','attributes':[attr('gen_ai.token.type','stringValue','output'),
                    attr('sentinel.pricing.key','stringValue','model.standard')]}]}},
            {'name':'gen_ai.client.operation.duration','histogram':{'dataPoints':[{'count':'1','sum':0.25}]}},
            {'name':'gen_ai.tool.call.duration','histogram':{'dataPoints':[{'count':'1','sum':0.1}]}},
            {'name':'gen_ai.retrieval.duration','histogram':{'dataPoints':[{'count':'1','sum':0.05}]}}
        ]}]}]}
        encoded=json.dumps(payload).encode()
        _,decoded,raw,media=decode_otlp('metrics',gzip.compress(encoded),'application/json; charset=utf-8','gzip')
        result=summarize_metrics(decoded)
        self.assertEqual(result['tokens'],{'input':12,'output':4})
        self.assertEqual(result['priced_tokens']['model.standard']['input_tokens'],12)
        self.assertEqual(result['latency_ms']['model']['sum'],250.0)
        self.assertEqual(result['latency_ms']['tool']['sum'],100.0)
        self.assertEqual(result['latency_ms']['retrieval']['sum'],50.0)
        self.assertNotIn('PRIVATE',str(result))
        self.assertEqual(raw,encoded); self.assertEqual(media,'application/json')

    def test_binary_trace_preserves_hex_ids_and_binary_success_type(self):
        request=ExportTraceServiceRequest(resource_spans=[ResourceSpans(
            scope_spans=[ScopeSpans(spans=[Span(trace_id=bytes.fromhex('a'*32),
                span_id=bytes.fromhex('b'*16),name='run',start_time_unix_nano=1,
                end_time_unix_nano=2)])])])
        _,payload,_,media=decode_otlp('traces',request.SerializeToString(),
                                     'application/x-protobuf',None)
        span=payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
        self.assertEqual(span['traceId'],'a'*32); self.assertEqual(span['spanId'],'b'*16)
        body,response_type=otlp_success('traces',media)
        self.assertEqual(body,b''); self.assertEqual(response_type,'application/x-protobuf')

    def test_logs_store_only_counts_and_discard_bodies_and_attributes(self):
        payload={'resourceLogs':[{'scopeLogs':[{'logRecords':[
            {'severityNumber':17,'traceId':'a'*32,'body':{'stringValue':'PRIVATE'},
             'attributes':[attr('secret','stringValue','PRIVATE')]},
            {'severityNumber':9,'body':{'stringValue':'PRIVATE-2'}}]}]}]}
        result=summarize_logs(payload)
        self.assertEqual(result['record_count'],2)
        self.assertEqual(result['severity_counts']['error'],1)
        self.assertEqual(result['correlated_trace_count'],1)
        self.assertNotIn('PRIVATE',str(result))

    def test_rejects_unsupported_encoding_type_bad_gzip_and_decoded_bomb(self):
        cases=[(b'{}','text/plain',None),(b'bad','application/json','gzip'),
               (gzip.compress(b'x'*(4*1024*1024+1)),'application/json','gzip')]
        for body,content_type,encoding in cases:
            with self.subTest(content_type=content_type,encoding=encoding),self.assertRaises(HTTPException):
                decode_otlp('metrics',body,content_type,encoding)


if __name__=='__main__': unittest.main()
