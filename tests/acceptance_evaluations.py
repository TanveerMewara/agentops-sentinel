"""Real PostgreSQL acceptance using synthetic saved-run facts, never bookings."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import copy
import subprocess
import sys
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.security import digest_key
from sentinel.evaluations import digest


def main():
    dev.setup()
    config = dev.load_config()
    app = create_app(Settings(database_url=native_postgres.dsn(), auth_pepper=config["auth_pepper"],
        booking_service_url="http://127.0.0.1:8002", credential_encryption_key=config["credential_encryption_key"]))
    client = TestClient(app)
    developer = {"X-API-Key": config["keys"]["developer"]}
    reviewer = {"X-API-Key": config["keys"]["reviewer"]}
    worker = {"X-API-Key": config["keys"]["worker"]}
    marker = uuid4().hex
    agent = client.post("/v1/agents", headers=developer, json={"slug": "eval_" + marker,
        "display_name": "Synthetic evaluation fixture"})
    assert agent.status_code == 201, agent.text
    version = client.post(f"/v1/agents/{agent.json()['agent_id']}/versions", headers=developer,
        json={"version": "1.0.0", "instructions": "Synthetic fixture; do not execute.", "model_alias": "deterministic_estateflow"})
    assert version.status_code == 201, version.text
    created = client.post("/v1/runs", headers=developer, json={"idempotency_key": "fixture-" + marker,
        "agent_version_id": version.json()["agent_version_id"], "input": {"customer": "PRIVATE-CONTACT-" + marker}})
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    dataset_body = {"slug": "regression-" + marker, "version": 1, "cases": [
        {"case_key": "business-outcome", "expected": {"run_status": "succeeded", "completed_bookings": 0,
            "property_bound": False, "max_model_tokens": 0, "followup_status": "not_created"}}]}
    # Seed the exact old schema shape to test replay across evaluator upgrades.
    legacy_body={'slug':'legacy-'+marker,'version':1,'cases':[{'case_key':'outcome','expected':{'run_status':'succeeded'}}]}
    legacy_definition={'slug':legacy_body['slug'],'version':1,'cases':[{'case_key':'outcome','expected':{
        'run_status':'succeeded','completed_bookings':None,'property_bound':None,'approvals_consumed':None,
        'review_required':None,'followup_status':None,'max_steps_used':None,'max_model_tokens':None,'max_model_duration_ms':None}}]}
    legacy_id=uuid4()
    with app.state.database.connect() as connection:
        identity=client.get('/v1/me',headers=developer).json()
        actor=connection.execute('SELECT api_key_id FROM sentinel_api_keys WHERE organization_id=%s AND key_prefix=%s',
            (identity['organization_id'],'_'.join(config['keys']['developer'].split('_')[:2]))).fetchone()
        connection.execute('INSERT INTO sentinel_evaluation_datasets (dataset_id,organization_id,slug,version,definition,content_hash,created_by_key_id) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (legacy_id,identity['organization_id'],legacy_body['slug'],1,Jsonb(legacy_definition),digest(legacy_definition),actor['api_key_id']))
    legacy_replay=client.post('/v1/evaluations/datasets',headers=developer,json=legacy_body)
    assert legacy_replay.status_code==200 and legacy_replay.json()['dataset_id']==str(legacy_id),legacy_replay.text
    path = "/v1/evaluations/datasets"
    assert client.post(path, headers=reviewer, json=dataset_body).status_code == 403
    dataset = client.post(path, headers=developer, json=dataset_body)
    assert dataset.status_code == 201, dataset.text
    assert client.post(path, headers=developer, json=dataset_body).status_code == 200
    altered = {**dataset_body, "cases": [{"case_key": "business-outcome", "expected": {"run_status": "failed"}}]}
    assert client.post(path, headers=developer, json=altered).status_code == 409
    experiment_body = {"idempotency_key": "experiment-" + marker, "dataset_id": dataset.json()["dataset_id"],
        "bindings": {"business-outcome": run_id}}
    experiments_path = "/v1/evaluations/experiments"
    assert client.post(experiments_path, headers=worker, json=experiment_body).status_code == 403
    assert client.post(experiments_path, headers=developer, json=experiment_body).status_code == 409
    assert client.post(f"/v1/runs/{run_id}/complete", headers=worker, json={}).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(experiments_path, headers=developer, json=experiment_body), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 201], [response.text for response in responses]
    report = responses[0].json()
    assert report == responses[1].json() and report["gate"]["passed"]
    assert client.post(experiments_path, headers=developer, json={**experiment_body, "min_pass_rate": 0.5}).status_code == 409
    foreign_org, foreign_key = uuid4(), uuid4()
    foreign_prefix = "snt_foreign" + marker
    foreign_token = foreign_prefix + "_" + uuid4().hex
    with app.state.database.connect() as connection:
        org = connection.execute("SELECT organization_id, api_key_id FROM sentinel_api_keys WHERE key_prefix=%s",
                                 ("_".join(config["keys"]["developer"].split("_")[:2]),)).fetchone()
        connection.execute("INSERT INTO sentinel_organizations (organization_id,name) VALUES (%s,%s)", (foreign_org, "Synthetic other tenant"))
        connection.execute("INSERT INTO sentinel_api_keys (api_key_id,organization_id,key_prefix,key_digest,label,role) VALUES (%s,%s,%s,%s,%s,'developer')",
            (foreign_key, foreign_org, foreign_prefix, digest_key(foreign_token, config["auth_pepper"]), "Synthetic tenant key"))
        # Explicit test-only mutation verifies that reports contain frozen facts.
        connection.execute("UPDATE sentinel_runs SET status='failed' WHERE run_id=%s", (run_id,))
        connection.execute("INSERT INTO sentinel_run_events (run_id,organization_id,event_type,details,actor_key_id) VALUES (%s,%s,%s,%s,%s)",
            (run_id, org["organization_id"], "fixture.sensitive_payload", Jsonb({"customer": "PRIVATE-CONTACT-" + marker}), org["api_key_id"]))
    assert client.post(experiments_path, headers=developer, json=experiment_body).json() == report
    failed = client.post(experiments_path, headers=reviewer, json={**experiment_body, "idempotency_key": "failed-" + marker})
    assert failed.status_code == 201 and not failed.json()["gate"]["passed"], failed.text
    compare_path = f"/v1/evaluations/compare?left={report['experiment_id']}&right={failed.json()['experiment_id']}"
    assert client.get(compare_path, headers=developer).json()["pass_rate_delta"] == -1.0
    foreign = {"X-API-Key": foreign_token}
    assert client.get(path, headers=foreign).json() == []
    assert client.post(experiments_path, headers=foreign, json=experiment_body).status_code == 404
    assert client.get(compare_path, headers=foreign).status_code == 404
    assert client.get(f"/v1/runs/{run_id}/timeline", headers=foreign).status_code == 404
    trace = client.get(f"/v1/runs/{run_id}/timeline", headers=developer)
    assert trace.status_code == 200, trace.text
    assert "PRIVATE-CONTACT" not in trace.text and "arguments" not in json.dumps(trace.json()["timeline"])
    assert trace.json()["metrics"]["model_tokens"] == 0
    output_dir = ROOT / ".local" / "evaluation-acceptance"
    output_dir.mkdir(parents=True, exist_ok=True)
    for label, value, exit_code in (("passing", report, 0), ("failing", failed.json(), 1)):
        output_file = output_dir / f"{label}-{marker}.json"
        output_file.write_text(json.dumps(value), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluation_gate.py"), str(output_file)], capture_output=True, text=True)
        assert result.returncode == exit_code, result.stdout + result.stderr
    # A real externally executed agent needs no leads/properties/bookings.
    external_version=client.post(f"/v1/agents/{agent.json()['agent_id']}/versions",headers=developer,
        json={'version':'2.0.0','instructions':'External support classifier; no example graph.','model_alias':'external_agent'})
    assert external_version.status_code==201
    external=client.post('/v1/runs',headers=developer,json={'idempotency_key':'external-'+marker,
        'agent_version_id':external_version.json()['agent_version_id'],
        'input':{'workflow':'external_support_triage','topic':'technical'}})
    assert external.status_code==201
    external_id=external.json()['run_id']
    with TestClient(app) as workflow_client:
        for action in ('start','resume'):
            response=workflow_client.post(f'/v1/runs/{external_id}/workflow/{action}',headers=worker,json={})
            assert response.status_code==409,response.text
        assert workflow_client.get(f'/v1/runs/{external_id}/tool-calls',headers=developer).json()==[]
    assert client.post(f'/v1/runs/{external_id}/complete',headers=worker,json={}).status_code==200
    general_dataset=client.post(path,headers=developer,json={'slug':'general-'+marker,'version':1,
        'cases':[{'case_key':'support-outcome','expected':{'run_status':'succeeded','completed_tool_calls':0,
            'failed_tool_calls':0,'uncertain_tool_calls':0,'max_tool_calls':0,'max_model_tokens':0,
            'required_approvals_consumed':True}}]})
    assert general_dataset.status_code==201,general_dataset.text
    general_body={'idempotency_key':'general-report-'+marker,'dataset_id':general_dataset.json()['dataset_id'],
        'bindings':{'support-outcome':external_id}}
    with patch('sentinel.integrations.estateflow_evaluation.collect_facts',side_effect=AssertionError('Example collector must not run.')):
        general=client.post(experiments_path,headers=developer,json=general_body)
    assert general.status_code==201,general.text
    general_report=general.json()
    assert general_report['evaluator_version']=='agent_rules_v2' and general_report['gate']['passed']
    assert 'completed_bookings' not in general_report['cases'][0]['facts']
    assert client.post(experiments_path,headers=developer,json=general_body).json()==general_report
    assert client.post(experiments_path,headers=foreign,json=general_body).status_code==404
    general_file=output_dir / f'general-{marker}.json'
    general_file.write_text(json.dumps(general_report),encoding='utf-8')
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/'evaluation_gate.py'),str(general_file)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    # Output requirements use immutable external evidence and privacy-safe reports.
    output={'answer':'PRIVATE-OUTPUT-'+marker,'category':'billing','confidence':1}
    schema={'type':'object','required':['answer','category','confidence'],'additionalProperties':False,
        'properties':{'answer':{'type':'string','minLength':1},'category':{'enum':['billing']},'confidence':{'type':'integer','minimum':0,'maximum':1}}}
    trace_body={'idempotency_key':'output-trace-'+marker,'source':'synthetic_support',
        'started_at':'2026-09-18T12:00:00+00:00','duration_ms':100,'reported_status':'succeeded',
        'output':output,'spans':[
            {'span_id':'root','name':'agent.run','kind':'agent','status':'completed','start_offset_ms':0,'duration_ms':100},
            {'span_id':'retrieval','parent_id':'root','name':'retrieval.context','kind':'retrieval','status':'completed','start_offset_ms':5,'duration_ms':5},
            {'span_id':'model','parent_id':'root','name':'model.generate','kind':'model','status':'completed','start_offset_ms':10,'duration_ms':50,'input_tokens':10,'output_tokens':5},
            {'span_id':'tool','parent_id':'root','name':'tool.respond','kind':'tool','status':'completed','start_offset_ms':70,'duration_ms':20}]}
    trace=client.post(f'/v1/runs/{external_id}/external-trace',headers=developer,json=trace_body)
    assert trace.status_code==201,trace.text
    assert client.post(experiments_path,headers=developer,json=general_body).json()==general_report
    output_dataset_body={'slug':'output-'+marker,'version':1,'cases':[
        {'case_key':'exact-answer','expected':{'output_equals':output}},
        {'case_key':'structured-answer','expected':{'output_schema':schema}}]}
    output_dataset=client.post(path,headers=developer,json=output_dataset_body)
    assert output_dataset.status_code==201,output_dataset.text
    assert client.post(path,headers=developer,json=output_dataset_body).status_code==200
    output_body={'idempotency_key':'output-report-'+marker,'dataset_id':output_dataset.json()['dataset_id'],
        'bindings':{'exact-answer':external_id,'structured-answer':external_id}}
    good=client.post(experiments_path,headers=reviewer,json=output_body)
    assert good.status_code==201,good.text
    good_report=good.json()
    assert good_report['evaluator_version']=='agent_rules_v3' and good_report['gate']['passed']
    assert 'PRIVATE-OUTPUT' not in good.text and '"output"' not in good.text
    assert all(case['facts']['external_output_trust']=='caller_reported' for case in good_report['cases'])
    assert client.post(experiments_path,headers=reviewer,json=output_body).json()==good_report
    missing=client.post(experiments_path,headers=reviewer,json={**output_body,'idempotency_key':'missing-output-'+marker,
        'bindings':{'exact-answer':run_id,'structured-answer':run_id}})
    assert missing.status_code==201 and not missing.json()['gate']['passed'],missing.text
    assert all(check['reason']=='missing_external_output' for case in missing.json()['cases'] for check in case['checks'])
    compared=client.get(f"/v1/evaluations/compare?left={good_report['experiment_id']}&right={missing.json()['experiment_id']}",headers=reviewer)
    assert compared.status_code==200 and compared.json()['pass_rate_delta']==-1.0
    changed=copy.deepcopy(output_dataset_body); changed['cases'][0]['expected']['output_equals']={'answer':'incorrect'}
    assert client.post(path,headers=developer,json=changed).status_code==409
    changed['version']=2
    bad_dataset=client.post(path,headers=developer,json=changed)
    assert bad_dataset.status_code==201
    bad=client.post(experiments_path,headers=reviewer,json={**output_body,'dataset_id':bad_dataset.json()['dataset_id'],'idempotency_key':'wrong-output-'+marker})
    assert bad.status_code==201 and not bad.json()['gate']['passed'] and bad.json()['passed_cases']==1
    assert client.post(experiments_path,headers=foreign,json=output_body).status_code==404
    trajectory_expected={'required_trace_spans':['agent.run','retrieval.context','model.generate','tool.respond'],
        'ordered_trace_spans':['agent.run','retrieval.context','model.generate','tool.respond'],
        'forbidden_trace_spans':['tool.delete'],'external_reported_status':'succeeded',
        'max_external_duration_ms':100,'max_reported_external_tokens':15,
        'reported_model_usage_complete':True,'max_external_spans':4,'max_failed_trace_spans':0}
    trajectory_dataset=client.post(path,headers=developer,json={'slug':'trajectory-'+marker,'version':1,
        'cases':[{'case_key':'safe-path','expected':trajectory_expected}]})
    assert trajectory_dataset.status_code==201,trajectory_dataset.text
    trajectory_body={'idempotency_key':'trajectory-report-'+marker,'dataset_id':trajectory_dataset.json()['dataset_id'],
        'bindings':{'safe-path':external_id}}
    trajectory=client.post(experiments_path,headers=reviewer,json=trajectory_body)
    assert trajectory.status_code==201,trajectory.text
    trajectory_report=trajectory.json()
    assert trajectory_report['evaluator_version']=='agent_rules_v4' and trajectory_report['gate']['passed']
    assert all(check['expected'] is True and type(check['actual']) is bool for check in trajectory_report['cases'][0]['checks'])
    assert not any(name in trajectory.text for name in ('agent.run','retrieval.context','model.generate','tool.respond','tool.delete'))
    assert trajectory_report['cases'][0]['facts']['reported_external_model_tokens']==15
    assert client.post(experiments_path,headers=reviewer,json=trajectory_body).json()==trajectory_report
    missing_trajectory=client.post(experiments_path,headers=reviewer,json={**trajectory_body,
        'idempotency_key':'missing-trajectory-'+marker,'bindings':{'safe-path':run_id}})
    assert missing_trajectory.status_code==201 and not missing_trajectory.json()['gate']['passed']
    assert all(check['reason']=='missing_external_trace' for check in missing_trajectory.json()['cases'][0]['checks'])
    changed_trajectory={'slug':'trajectory-'+marker,'version':1,'cases':[{'case_key':'safe-path','expected':{
        **trajectory_expected,'required_trace_spans':['tool.archive']}}]}
    assert client.post(path,headers=developer,json=changed_trajectory).status_code==409
    changed_trajectory['version']=2
    bad_trajectory_dataset=client.post(path,headers=developer,json=changed_trajectory)
    assert bad_trajectory_dataset.status_code==201
    bad_trajectory=client.post(experiments_path,headers=reviewer,json={**trajectory_body,
        'idempotency_key':'bad-trajectory-'+marker,'dataset_id':bad_trajectory_dataset.json()['dataset_id']})
    assert bad_trajectory.status_code==201 and not bad_trajectory.json()['gate']['passed']
    comparison=client.get(f"/v1/evaluations/compare?left={trajectory_report['experiment_id']}&right={bad_trajectory.json()['experiment_id']}",headers=reviewer)
    assert comparison.status_code==409  # different immutable dataset versions
    assert client.post(experiments_path,headers=foreign,json=trajectory_body).status_code==404
    invalid={'slug':'invalid-'+marker,'version':1,'cases':[{'case_key':'output','expected':{'output_schema':{'$ref':'https://example.invalid/PRIVATE-SCHEMA'}}}]}
    failure=client.post(path,headers=developer,json=invalid)
    assert failure.status_code==422 and 'PRIVATE-SCHEMA' not in failure.text
    assert client.post(path,headers=developer,content=b' '*524289).status_code==413
    for label,report,code in [('good',good_report,0),('bad',bad.json(),1),('missing',missing.json(),1),
                              ('trajectory',trajectory_report,0),('bad-trajectory',bad_trajectory.json(),1)]:
        report_file=output_dir/f'output-{label}-{marker}.json'
        report_file.write_text(json.dumps(report),encoding='utf-8')
        result=subprocess.run([sys.executable,str(ROOT/'scripts'/'evaluation_gate.py'),str(report_file)],capture_output=True,text=True)
        assert result.returncode==code,result.stdout+result.stderr
    client.close()
    print("PASS: immutable datasets, output and trajectory evaluation, terminal-run checks, concurrent replay, frozen reports, failing gates, comparisons, tenant isolation, privacy-safe reports, gate CLI, general external-agent rules without business reads, and example-routing denial.")


if __name__ == "__main__":
    main()
