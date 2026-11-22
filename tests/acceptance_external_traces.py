"""Native PostgreSQL acceptance; synthetic domains, no live model calls."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import copy
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from agents import agent_span, function_span, generation_span, set_trace_processors, trace
from langgraph.graph import END, START, StateGraph

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.security import digest_key
from sentinel.trace_recorder import TraceRecorder
from sentinel.integrations.langchain_trace import SentinelLangChainCallback
from sentinel.integrations.openai_agents_trace import SentinelOpenAIAgentsProcessor


def main():
    dev.setup()
    config=dev.load_config()
    app=create_app(Settings(database_url=native_postgres.dsn(),auth_pepper=config['auth_pepper'],
        booking_service_url='http://127.0.0.1:8002',credential_encryption_key=config['credential_encryption_key']))
    headers={role:{'X-API-Key':token} for role,token in config['keys'].items()}
    marker=uuid4().hex
    otlp_payload=otlp_run_id=otlp_finalize_body=None
    stage2_runs={}
    with TestClient(app) as client:
        for domain,output in (('support',{'category':'billing','answer':'PRIVATE-OUTPUT-'+marker}),
                              ('code',{'findings':[{'rule':'unused_import','severity':'low'}]}),
                              ('langgraph',{'value':2}),
                              ('openai_agents',{'category':'technical','priority':'standard'}),
                              ('otlp',{'answer':'sanitized'})):
            agent=client.post('/v1/agents',headers=headers['developer'],json={
                'slug':'trace_'+domain+'_'+marker,'display_name':'Synthetic '+domain+' trace fixture'})
            assert agent.status_code==201
            version=client.post(f"/v1/agents/{agent.json()['agent_id']}/versions",headers=headers['developer'],json={
                'version':'1.0.0','instructions':'Externally executed synthetic fixture.',
                'model_alias':'external_agent','max_steps':12})
            assert version.status_code==201
            run=client.post('/v1/runs',headers=headers['developer'],json={
                'agent_version_id':version.json()['agent_version_id'],'idempotency_key':'trace-run-'+domain+'-'+marker,'input':{}})
            assert run.status_code==201
            run_id=run.json()['run_id']; path=f'/v1/runs/{run_id}/external-trace'
            write_path=path
            assert client.get(path,headers=headers['reviewer']).status_code==404
            if domain=='langgraph':
                builder=StateGraph(dict)
                builder.add_node('increment',lambda state:{'value':state.get('value',0)+1})
                builder.add_edge(START,'increment'); builder.add_edge('increment',END)
                callback=SentinelLangChainCallback(source='langgraph')
                output=builder.compile().invoke({'value':1},config={'callbacks':[callback]})
                body=callback.finish(output,idempotency_key='trace-final-'+domain+'-'+marker)
            elif domain=='openai_agents':
                processor=SentinelOpenAIAgentsProcessor()
                set_trace_processors([processor])
                try:
                    with trace('Synthetic OpenAI Agents SDK run') as sdk_trace:
                        with agent_span('support_agent'):
                            with generation_span(
                                input=[{'role':'user','content':'PRIVATE SDK PROMPT'}],
                                output=[{'role':'assistant','content':'PRIVATE SDK OUTPUT'}],
                                model='private-sdk-model',
                                usage={'input_tokens':11,'output_tokens':4}):
                                pass
                            with function_span('classify_ticket',input='PRIVATE SDK ARGUMENT',
                                               output='PRIVATE SDK TOOL RESULT'):
                                pass
                    body=processor.finish(output,trace_id=sdk_trace.trace_id,
                        idempotency_key='trace-final-'+domain+'-'+marker)
                finally:
                    set_trace_processors([])
            elif domain=='otlp':
                started=1700000000000000000
                trace_id='5b8efff798038103d269b633813fc60c'
                otlp={'resourceSpans':[{'scopeSpans':[{'spans':[
                    {'traceId':trace_id,'spanId':'0000000000000001','name':'Support flow',
                     'startTimeUnixNano':str(started),'endTimeUnixNano':str(started+5000000)},
                    {'traceId':trace_id,'spanId':'0000000000000002','parentSpanId':'0000000000000001',
                     'name':'chat private-model','startTimeUnixNano':str(started+1000000),
                     'endTimeUnixNano':str(started+4000000),'attributes':[
                         {'key':'gen_ai.operation.name','value':{'stringValue':'chat'}},
                         {'key':'gen_ai.usage.input_tokens','value':{'intValue':'7'}},
                         {'key':'gen_ai.usage.output_tokens','value':{'intValue':'3'}},
                         {'key':'gen_ai.input.messages','value':{'stringValue':'PRIVATE-OTLP'}}]}]}]}]}
                receiver_headers={**headers['worker'],'X-Sentinel-Run-Id':run_id}
                otlp_payload,otlp_run_id=otlp,run_id
                denied=client.post('/v1/traces',headers={**headers['reviewer'],
                    'X-Sentinel-Run-Id':run_id},json=otlp)
                assert denied.status_code==403
                invalid_otlp=copy.deepcopy(otlp)
                invalid_otlp['resourceSpans'][0]['scopeSpans'][0]['spans'][0]['spanId']='PRIVATE-OTLP-ID'
                rejected=client.post('/v1/traces',headers=receiver_headers,json=invalid_otlp)
                assert rejected.status_code==422 and 'PRIVATE-OTLP-ID' not in rejected.text
                with ThreadPoolExecutor(max_workers=2) as pool:
                    receipts=list(pool.map(lambda _:client.post('/v1/traces',
                        headers=receiver_headers,json=otlp),range(2)))
                assert all(reply.status_code==200 and reply.json()=={} for reply in receipts)
                assert client.get(path,headers=headers['reviewer']).status_code==404
                body={'idempotency_key':'trace-final-'+domain+'-'+marker,
                    'reported_status':'succeeded','output':output}
                otlp_finalize_body=body
                write_path=path+'/otlp/finalize'
            else:
                recorder=TraceRecorder(source='python_'+domain)
                with recorder.span('agent.run'):
                    with recorder.span('model.generate','model'): pass
                    with recorder.span('tool.classify','tool'): pass
                body=recorder.finish(output,reported_status='failed' if domain=='code' else 'succeeded',
                    idempotency_key='trace-final-'+domain+'-'+marker)
            assert client.post(write_path,headers=headers['reviewer'],json=body).status_code==403
            with ThreadPoolExecutor(max_workers=2) as pool:
                replies=list(pool.map(lambda _:client.post(write_path,headers=headers['worker'],json=body),range(2)))
            assert sorted(reply.status_code for reply in replies)==[200,201]
            assert replies[0].json()==replies[1].json()
            view=replies[0].json()
            assert view['trust']=='caller_reported' and not view['governed_execution_proof']
            assert view['usage']['complete_for_reported_model_spans'] is (domain in ('langgraph','openai_agents','otlp'))
            assert not view['usage']['all_external_activity_captured']
            assert 'output' not in view and 'PRIVATE-OUTPUT' not in str(view)
            assert 'PRIVATE-OTLP' not in str(view) and 'private-model' not in str(view)
            assert 'PRIVATE SDK' not in str(view) and 'private-sdk-model' not in str(view)
            altered=copy.deepcopy(body); altered['output']={'changed':True}
            assert client.post(write_path,headers=headers['developer'],json=altered).status_code==409
            altered=copy.deepcopy(body); altered['idempotency_key']+='-other'
            assert client.post(write_path,headers=headers['developer'],json=altered).status_code==409
            for role in ('admin','developer','reviewer','worker'):
                read=client.get(path,headers=headers[role]); assert read.status_code==200 and read.json()==view
            assert client.get(path+'?include_output=true',headers=headers['reviewer']).json()['output']==output
            assert client.get(path,headers=headers['reviewer']).headers['cache-control']=='no-store'
            assert client.get(f'/v1/runs/{run_id}',headers=headers['developer']).json()['status']=='queued'
            stage2_runs[domain]={'run_id':run_id,'output':output,
                'reported_status':body['reported_status']}
            if domain=='otlp':
                assert client.post('/v1/traces',headers=receiver_headers,json=otlp).status_code==409
            with app.state.database.connect() as connection:
                assert connection.execute('SELECT count(*) AS n FROM sentinel_run_events WHERE run_id=%s AND event_type=%s',
                    (run_id,'external_trace.recorded')).fetchone()['n']==1
                assert connection.execute('SELECT count(*) AS n FROM sentinel_tool_calls WHERE run_id=%s',(run_id,)).fetchone()['n']==0
                assert connection.execute('SELECT count(*) AS n FROM sentinel_model_invocations WHERE run_id=%s',(run_id,)).fetchone()['n']==0
                if domain=='otlp':
                    assert connection.execute('SELECT count(*) AS n FROM sentinel_pending_otlp_traces WHERE run_id=%s',(run_id,)).fetchone()['n']==1
                    assert connection.execute('SELECT count(*) AS n FROM sentinel_run_events WHERE run_id=%s AND event_type=%s',
                        (run_id,'external_trace.otlp_received')).fetchone()['n']==1
            timeline=client.get(f'/v1/runs/{run_id}/timeline',headers=headers['reviewer'])
            assert timeline.status_code==200 and 'PRIVATE-OUTPUT' not in timeline.text
            invalid=copy.deepcopy(body)
            if domain=='otlp':
                invalid['PRIVATE-VALIDATION-'+marker]=True
            else:
                invalid['spans'][0]['parent_id']='PRIVATE-VALIDATION-'+marker
            failure=client.post(write_path,headers=headers['developer'],json=invalid)
            assert failure.status_code==422 and 'PRIVATE-VALIDATION' not in failure.text and 'PRIVATE-OUTPUT' not in failure.text
            invalid=copy.deepcopy(body); invalid['output']={'value':'界'*23000}
            failure=client.post(write_path,headers=headers['developer'],json=invalid)
            assert failure.status_code==422 and '界' not in failure.text
            oversized=client.post(write_path,headers=headers['developer'],content=b'PRIVATE-TRANSPORT'+b' '*131073)
            assert oversized.status_code==413 and 'PRIVATE-TRANSPORT' not in oversized.text
            assert oversized.headers['cache-control']=='no-store'
            chunks=(b' '*70000 for _ in range(2))
            oversized=client.post(write_path,headers=headers['developer'],content=chunks)
            assert oversized.status_code==413
            if domain=='support': saved_path=path; saved_body=body
        dataset_body={'slug':'stage2-frameworks-'+marker,'version':1,'cases':[
            {'case_key':domain,'expected':{'output_equals':item['output'],
                'external_reported_status':item['reported_status']}}
            for domain,item in stage2_runs.items()]}
        dataset=client.post('/v1/evaluations/datasets',headers=headers['developer'],json=dataset_body)
        assert dataset.status_code==201,dataset.text
        for item in stage2_runs.values():
            completed=client.post(f"/v1/runs/{item['run_id']}/complete",
                headers=headers['worker'],json={})
            assert completed.status_code==200,completed.text
        experiment=client.post('/v1/evaluations/experiments',headers=headers['developer'],json={
            'idempotency_key':'stage2-framework-report-'+marker,
            'dataset_id':dataset.json()['dataset_id'],
            'bindings':{domain:item['run_id'] for domain,item in stage2_runs.items()}})
        assert experiment.status_code==201,experiment.text
        assert experiment.json()['evaluator_version']=='agent_rules_v4'
        assert experiment.json()['gate']['passed']
        assert len(experiment.json()['cases'])==len(stage2_runs)
        foreign_org=uuid4(); foreign_key=uuid4(); prefix='snt_trace'+marker; token=prefix+'_'+uuid4().hex
        with app.state.database.connect() as connection:
            connection.execute('INSERT INTO sentinel_organizations (organization_id,name) VALUES (%s,%s)',
                (foreign_org,'Trace foreign fixture'))
            connection.execute('INSERT INTO sentinel_api_keys (api_key_id,organization_id,label,role,key_prefix,key_digest) VALUES (%s,%s,%s,%s,%s,%s)',
                (foreign_key,foreign_org,'Trace foreign','developer',prefix,digest_key(token,config['auth_pepper'])))
        foreign={'X-API-Key':token}
        assert client.get(saved_path+'?include_output=true',headers=foreign).status_code==404
        assert client.post(saved_path,headers=foreign,json=saved_body).status_code==404
        assert client.post('/v1/traces',headers={**foreign,
            'X-Sentinel-Run-Id':otlp_run_id},json=otlp_payload).status_code==404
        assert client.post(f'/v1/runs/{otlp_run_id}/external-trace/otlp/finalize',
            headers=foreign,json=otlp_finalize_body).status_code==404
        assert client.get(saved_path).status_code==401
        # Explicit example runs cannot attach external evidence even under a neutral alias.
        example=client.post('/v1/runs',headers=headers['developer'],json={
            'agent_version_id':version.json()['agent_version_id'],'idempotency_key':'example-trace-'+marker,
            'input':{'workflow':'estateflow'}})
        assert client.post(f"/v1/runs/{example.json()['run_id']}/external-trace",headers=headers['developer'],json=saved_body).status_code==409
    print('PASS: five external-agent domains, real LangGraph and OpenAI Agents SDK traces, standard OTLP receipt/finalization, one passing v4 cross-framework evaluation, immutable replay, privacy, tenant isolation, and unchanged governed tool/model ledgers.')


if __name__=='__main__': main()
