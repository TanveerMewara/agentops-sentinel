"""Native PostgreSQL acceptance for Stage 3 OTLP telemetry."""
import gzip
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.metrics.v1.metrics_pb2 import Metric, NumberDataPoint, ResourceMetrics, ScopeMetrics, Sum
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app


def kv(key,value):
    return KeyValue(key=key,value=AnyValue(string_value=value))


def main():
    dev.setup(); config=dev.load_config(); marker=uuid4().hex
    app=create_app(Settings(database_url=native_postgres.dsn(),auth_pepper=config['auth_pepper'],
        booking_service_url='http://127.0.0.1:8002',credential_encryption_key=config['credential_encryption_key']))
    headers={role:{'X-API-Key':token} for role,token in config['keys'].items()}
    with TestClient(app) as client:
        agent=client.post('/v1/agents',headers=headers['developer'],json={
            'slug':'telemetry_'+marker,'display_name':'Telemetry acceptance fixture'})
        assert agent.status_code==201,agent.text
        version=client.post(f"/v1/agents/{agent.json()['agent_id']}/versions",headers=headers['developer'],json={
            'version':'1.0.0','instructions':'Synthetic external telemetry fixture.',
            'model_alias':'external_agent','max_steps':12})
        run=client.post('/v1/runs',headers=headers['developer'],json={
            'agent_version_id':version.json()['agent_version_id'],
            'idempotency_key':'telemetry-run-'+marker,'input':{}})
        run_id=run.json()['run_id']; pricing_key='model.'+marker[:12]

        policy=client.put('/v1/telemetry/policy',headers=headers['admin'],json={
            'retention_days':7,'required_signals':['traces','metrics','logs'],
            'require_token_usage':True,'require_cost':True})
        assert policy.status_code==200,policy.text
        rate=client.post('/v1/telemetry/rate-cards',headers=headers['admin'],json={
            'pricing_key':pricing_key,'input_usd_per_million':'1.00000000',
            'output_usd_per_million':'2.00000000'})
        assert rate.status_code==201 and rate.json()['version']==1,rate.text
        cards=client.get('/v1/telemetry/rate-cards',headers=headers['reviewer'])
        assert cards.status_code==200 and any(x['pricing_key']==pricing_key and x['version']==1 for x in cards.json())

        trace=ExportTraceServiceRequest(resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[
            Span(trace_id=bytes.fromhex('a'*32),span_id=bytes.fromhex('1'*16),name='run',
                 start_time_unix_nano=1_700_000_000_000_000_000,end_time_unix_nano=1_700_000_000_010_000_000),
            Span(trace_id=bytes.fromhex('a'*32),span_id=bytes.fromhex('2'*16),parent_span_id=bytes.fromhex('1'*16),
                 name='chat private-model',start_time_unix_nano=1_700_000_000_001_000_000,
                 end_time_unix_nano=1_700_000_000_005_000_000,
                 attributes=[kv('gen_ai.operation.name','chat')])])])])
        otlp_headers={**headers['worker'],'X-Sentinel-Run-Id':run_id,
                      'Content-Type':'application/x-protobuf'}
        received=client.post('/v1/traces',headers=otlp_headers,content=trace.SerializeToString())
        assert received.status_code==200 and received.content==b'',received.text
        assert received.headers['content-type']=='application/x-protobuf'

        points=[NumberDataPoint(as_int=12,attributes=[kv('gen_ai.token.type','input'),kv('sentinel.pricing.key',pricing_key)]),
                NumberDataPoint(as_int=4,attributes=[kv('gen_ai.token.type','output'),kv('sentinel.pricing.key',pricing_key)])]
        metrics=ExportMetricsServiceRequest(resource_metrics=[ResourceMetrics(scope_metrics=[ScopeMetrics(metrics=[
            Metric(name='gen_ai.client.token.usage',unit='{token}',sum=Sum(data_points=points,aggregation_temporality=2,is_monotonic=True))])])])
        metric_body=metrics.SerializeToString()
        metric=client.post('/v1/metrics',headers=otlp_headers,content=metric_body)
        assert metric.status_code==200 and metric.content==b'',metric.text
        assert client.post('/v1/metrics',headers=otlp_headers,content=metric_body).status_code==200

        logs={'resourceLogs':[{'scopeLogs':[{'logRecords':[{
            'timeUnixNano':'1700000000000000000','severityNumber':17,'traceId':'a'*32,
            'spanId':'2'*16,'body':{'stringValue':'PRIVATE LOG '+marker},
            'attributes':[{'key':'secret','value':{'stringValue':'PRIVATE ATTRIBUTE'}}]}]}]}]}
        log_headers={**headers['worker'],'X-Sentinel-Run-Id':run_id,
                     'Content-Type':'application/json','Content-Encoding':'gzip'}
        logged=client.post('/v1/logs',headers=log_headers,content=gzip.compress(json.dumps(logs).encode()))
        assert logged.status_code==200 and logged.json()=={},logged.text

        view=client.get(f'/v1/runs/{run_id}/telemetry',headers=headers['reviewer'])
        assert view.status_code==200,view.text
        summary=view.json(); assert summary['complete'] is True and summary['gaps']==[]
        assert summary['signals']==['logs','metrics','traces'] and summary['tokens']['total']==16
        assert summary['estimated_cost_usd']=='0.00002000' and summary['batch_count']==3
        assert summary['latency_ms']['model']['count']==0
        assert 'PRIVATE' not in str(summary)

        with app.state.database.connect() as connection:
            stored=str(connection.execute('SELECT summary FROM sentinel_telemetry_batches WHERE run_id=%s',(run_id,)).fetchall())
            assert 'PRIVATE' not in stored
            connection.execute('UPDATE sentinel_telemetry_batches SET expires_at=now()-interval \'1 second\' WHERE run_id=%s',(run_id,))
        purged=client.post('/v1/telemetry/retention/purge',headers=headers['admin'],json={})
        assert purged.json()['deleted_batches']==2
        incomplete=client.get(f'/v1/runs/{run_id}/telemetry',headers=headers['reviewer']).json()
        assert incomplete['complete'] is False and {'missing_metrics','missing_logs','missing_token_usage','missing_cost'}<=set(incomplete['gaps'])

        assert client.post('/v1/metrics',headers=otlp_headers,content=metric_body).status_code==200
        assert client.post('/v1/logs',headers=log_headers,content=gzip.compress(json.dumps(logs).encode())).status_code==200
        denied=client.delete(f'/v1/runs/{run_id}/telemetry',headers=headers['developer'])
        assert denied.status_code==403
        deleted=client.delete(f'/v1/runs/{run_id}/telemetry',headers=headers['admin'])
        assert deleted.status_code==200 and deleted.json()['deleted_batches']==2
        assert deleted.json()['deleted_pending_traces']==1 and deleted.json()['finalized_external_evidence_deleted'] is False

        restored=client.put('/v1/telemetry/policy',headers=headers['admin'],json={
            'retention_days':30,'required_signals':['traces'],
            'require_token_usage':False,'require_cost':False})
        assert restored.status_code==200
    print('Stage 3 telemetry acceptance passed: protobuf, gzip, signals, cost, completeness, retention and deletion.')


if __name__=='__main__': main()
