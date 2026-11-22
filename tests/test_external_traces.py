import unittest
import asyncio

from pydantic import ValidationError

from sentinel.external_traces import ExternalTraceCreate, trace_view
from sentinel.trace_recorder import TraceRecorder
from sentinel.http_security import ExternalTraceBodyLimit


def evidence():
    return {"idempotency_key":"trace-fixture-01", "source":"python_agent",
        "started_at":"2026-09-18T12:00:00+00:00", "duration_ms":100,
        "reported_status":"succeeded", "output":{"answer":"PRIVATE-OUTPUT"},
        "spans":[{"span_id":"root","parent_id":None,"name":"agent.run","kind":"agent",
            "status":"completed","start_offset_ms":0,"duration_ms":100},
            {"span_id":"model","parent_id":"root","name":"model.generate","kind":"model",
            "status":"completed","start_offset_ms":10,"duration_ms":60}]}


class ExternalTraceTests(unittest.TestCase):
    def test_transport_limit_counts_separate_asgi_chunks_before_dispatch(self):
        dispatched=[]; sent=[]
        messages=iter([{'type':'http.request','body':b' '*70000,'more_body':True},
            {'type':'http.request','body':b' '*70000,'more_body':False}])
        async def receive(): return next(messages)
        async def send(message): sent.append(message)
        async def app(scope,receive,send): dispatched.append(True)
        asyncio.run(ExternalTraceBodyLimit(app)({'type':'http','method':'POST',
            'path':'/v1/runs/fixture/external-trace'},receive,send))
        self.assertFalse(dispatched)
        self.assertEqual(sent[0]['status'],413)

    def test_small_transport_body_is_reassembled_without_dispatch_changes(self):
        bodies=[]
        messages=iter([{'type':'http.request','body':b'{','more_body':True},
            {'type':'http.request','body':b'}','more_body':False}])
        async def receive(): return next(messages)
        async def send(message): pass
        async def app(scope,receive,send): bodies.append((await receive())['body'])
        asyncio.run(ExternalTraceBodyLimit(app)({'type':'http','method':'POST',
            'path':'/v1/runs/fixture/external-trace'},receive,send))
        self.assertEqual(bodies,[b'{}'])

    def test_otlp_import_uses_the_same_transport_limit(self):
        for path in ('/v1/runs/fixture/external-trace/otlp',
                     '/v1/runs/fixture/external-trace/otlp/finalize'):
            dispatched=[]; sent=[]
            messages=iter([{'type':'http.request','body':b' '*131073,'more_body':False}])
            async def receive(): return next(messages)
            async def send(message): sent.append(message)
            async def app(scope,receive,send): dispatched.append(True)
            asyncio.run(ExternalTraceBodyLimit(app)({'type':'http','method':'POST',
                'path':path},receive,send))
            self.assertFalse(dispatched)
            self.assertEqual(sent[0]['status'],413)

    def test_standard_otlp_paths_use_a_one_mib_compressed_transport_limit(self):
        for path in ('/v1/traces','/v1/metrics','/v1/logs'):
            dispatched=[]; sent=[]
            messages=iter([{'type':'http.request','body':b' '*(1048577),'more_body':False}])
            async def receive(): return next(messages)
            async def send(message): sent.append(message)
            async def app(scope,receive,send): dispatched.append(True)
            asyncio.run(ExternalTraceBodyLimit(app)({'type':'http','method':'POST',
                'path':path},receive,send))
            self.assertFalse(dispatched)
            self.assertEqual(sent[0]['status'],413)

    def test_valid_evidence_and_default_output_redaction(self):
        body=ExternalTraceCreate.model_validate(evidence())
        row={"trace_id":"trace", "run_id":"run", "idempotency_key":body.idempotency_key,
            "content_hash":"hash", "created_at":"now", "evidence":body.model_dump(mode="json")}
        view=trace_view(row)
        self.assertNotIn("PRIVATE-OUTPUT",str(view))
        self.assertEqual(view['trust'],'caller_reported')
        self.assertFalse(view['governed_execution_proof'])
        self.assertFalse(view['usage']['complete_for_reported_model_spans'])
        self.assertFalse(view['usage']['all_external_activity_captured'])
        self.assertEqual(trace_view(row,include_output=True)['output'],body.output)

    def test_rejects_invalid_span_trees(self):
        invalid=[]
        for parent in ('missing','model'):
            body=evidence(); body['spans'][1]['parent_id']=parent; invalid.append(body)
        body=evidence(); body['spans'][0]['parent_id']='model'; invalid.append(body)
        body=evidence(); body['spans'][1]['span_id']='root'; invalid.append(body)
        body=evidence(); body['spans'][1]['duration_ms']=200; invalid.append(body)
        body=evidence(); body['spans'][0]['start_offset_ms']=20; body['spans'][0]['duration_ms']=80; invalid.append(body)
        for body in invalid:
            with self.subTest(body=body),self.assertRaises(ValidationError):
                ExternalTraceCreate.model_validate(body)

    def test_usage_is_explicit_and_model_only(self):
        body=evidence(); body['spans'][1].update(input_tokens=0,output_tokens=7)
        ExternalTraceCreate.model_validate(body)
        for change in ({'input_tokens':1}, {'input_tokens':True,'output_tokens':2}, {'input_tokens':-1,'output_tokens':1}):
            body=evidence(); body['spans'][1].update(change)
            with self.assertRaises(ValidationError): ExternalTraceCreate.model_validate(body)
        body=evidence(); body['spans'][0].update(input_tokens=1,output_tokens=2)
        with self.assertRaises(ValidationError): ExternalTraceCreate.model_validate(body)

    def test_size_finite_json_and_aware_time_limits(self):
        for value in ('x'*66000, '界'*23000, float('nan'), float('inf')):
            body=evidence(); body['output']={'value':value}
            with self.assertRaises(ValidationError): ExternalTraceCreate.model_validate(body)
        body=evidence(); body['started_at']='2026-09-18T12:00:00'
        with self.assertRaises(ValidationError): ExternalTraceCreate.model_validate(body)
        body=evidence(); body['spans']=body['spans']*51
        with self.assertRaises(ValidationError): ExternalTraceCreate.model_validate(body)

    def test_recorder_nested_spans_missing_usage_and_finalize_once(self):
        recorder=TraceRecorder()
        with recorder.span('agent.run'):
            with recorder.span('model.generate','model') as model:
                model.update(input_tokens=3,output_tokens=4)
            with self.assertRaises(ValueError): recorder.finish({})
        result=recorder.finish({'category':'support'},idempotency_key='trace-demo-key')
        body=ExternalTraceCreate.model_validate(result)
        self.assertEqual(body.spans[0].parent_id,body.spans[1].span_id)
        with self.assertRaises(ValueError): recorder.finish({})
        with self.assertRaises(ValueError):
            with recorder.span('again'): pass

    def test_recorder_exception_records_status_without_message(self):
        recorder=TraceRecorder()
        with self.assertRaises(RuntimeError):
            with recorder.span('agent.run'): raise RuntimeError('PRIVATE-EXCEPTION')
        result=recorder.finish({},reported_status='failed')
        self.assertEqual(result['spans'][0]['status'],'failed')
        self.assertNotIn('PRIVATE-EXCEPTION',str(result))


if __name__=='__main__': unittest.main()
