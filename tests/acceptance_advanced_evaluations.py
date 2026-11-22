"""Real PostgreSQL/API acceptance for Stage 4 evaluation and release gates."""
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.semantic_judge import JudgeResult


class ScriptedJudge:
    def evaluate(self,organization_id,model_alias,criterion,reference,output):
        score=float(output['quality'])
        return JudgeResult(score,'pass' if score>=0.5 else 'fail',(),12,4,5,'scripted-judge-v1')


def main():
    dev.setup(); config=dev.load_config(); marker=uuid4().hex
    app=create_app(Settings(database_url=native_postgres.dsn(),auth_pepper=config['auth_pepper'],
        booking_service_url='http://127.0.0.1:8002',credential_encryption_key=config['credential_encryption_key']),
        semantic_judge=ScriptedJudge())
    headers={role:{'X-API-Key':token} for role,token in config['keys'].items()}
    with TestClient(app) as client:
        agent=client.post('/v1/agents',headers=headers['developer'],json={
            'slug':'stage4_'+marker,'display_name':'Stage 4 synthetic fixture'}).json()
        version=client.post(f"/v1/agents/{agent['agent_id']}/versions",headers=headers['developer'],json={
            'version':'1.0.0','instructions':'External synthetic evaluation fixture.','model_alias':'external_agent'}).json()
        runs=[]
        for index in range(3):
            run=client.post('/v1/runs',headers=headers['developer'],json={
                'agent_version_id':version['agent_version_id'],'idempotency_key':f'stage4-run-{index}-{marker}','input':{}})
            assert run.status_code==201,run.text
            run_id=run.json()['run_id']; runs.append(run_id)
            assert client.post(f'/v1/runs/{run_id}/complete',headers=headers['worker'],json={}).status_code==200
            trace={'idempotency_key':f'stage4-trace-{index}-{marker}','source':'stage4_fixture',
                'started_at':'2026-09-21T12:00:00+00:00','duration_ms':10,'reported_status':'succeeded',
                'output':{'answer':'PRIVATE-ANSWER-'+marker,'quality':0.9},'spans':[
                    {'span_id':'root','name':'agent.run','kind':'agent','status':'completed','start_offset_ms':0,'duration_ms':10}]}
            saved=client.post(f'/v1/runs/{run_id}/external-trace',headers=headers['developer'],json=trace)
            assert saved.status_code==201,saved.text

        rubric={'criterion':'Judge whether the answer correctly and safely resolves the supplied synthetic task.',
            'reference':{'answer':'A correct and safe answer.'},'min_score':0.8,
            'model_alias':'eval_judge','repetitions':3}
        cases=[{'case_key':key,'category':category,'split':'test','expected':{'semantic_judge':rubric}}
               for key,category in [('billing-case','billing'),('technical-case','technical'),('safety-case','safety')]]
        dataset=client.post('/v1/evaluations/datasets',headers=headers['developer'],json={
            'slug':'stage4-heldout-'+marker,'version':1,'coverage':{'min_categories':3,'min_cases_per_category':1},
            'cases':cases})
        assert dataset.status_code==201,dataset.text
        bindings={case['case_key']:run_id for case,run_id in zip(cases,runs)}
        reports=[]
        for index in range(2):
            response=client.post('/v1/evaluations/experiments',headers=headers['developer'],json={
                'idempotency_key':f'stage4-experiment-{index}-{marker}','dataset_id':dataset.json()['dataset_id'],
                'bindings':bindings,'variant':{'prompt_version':f'prompt-{index+1}','model_alias':'external_agent',
                    'retrieval_version':'retrieval-1'}})
            assert response.status_code==201,response.text
            report=response.json(); reports.append(report)
            assert report['evaluator_version']=='agent_rules_v5' and report['gate']['passed']
            assert report['dataset_profile']['held_out'] and len(report['dataset_profile']['categories'])==3
            assert 'PRIVATE-ANSWER' not in response.text and 'correctly and safely' not in response.text
            assert all(check['repetitions']==3 for case in report['cases'] for check in case['checks'])

        analysis=client.post('/v1/evaluations/analysis',headers=headers['reviewer'],json={
            'experiment_ids':[item['experiment_id'] for item in reports]})
        assert analysis.status_code==200,analysis.text
        assert analysis.json()['experiment_count']==2 and analysis.json()['mean_pass_rate']==1
        assert analysis.json()['pass_rate_stddev']==0 and analysis.json()['held_out'] is True
        assert client.post('/v1/evaluations/experiments',headers=headers['reviewer'],json={
            'idempotency_key':'semantic-reviewer-denied-'+marker,'dataset_id':dataset.json()['dataset_id'],
            'bindings':bindings}).status_code==403

        for case,run_id in zip(cases,runs):
            label=client.post('/v1/evaluations/human-labels',headers=headers['reviewer'],json={
                'dataset_id':dataset.json()['dataset_id'],'case_key':case['case_key'],'run_id':run_id,
                'score':'0.9000','label':'pass'})
            assert label.status_code==201,label.text
            assert client.post('/v1/evaluations/human-labels',headers=headers['reviewer'],json={
                'dataset_id':dataset.json()['dataset_id'],'case_key':case['case_key'],'run_id':run_id,
                'score':'0.9000','label':'pass'}).status_code==200
        calibration=client.post('/v1/evaluations/calibrations',headers=headers['reviewer'],json={
            'experiment_id':reports[0]['experiment_id'],'min_labels':3,
            'max_mean_absolute_error':0.1,'min_label_agreement':1.0})
        assert calibration.status_code==201 and calibration.json()['passed'],calibration.text
        assert calibration.json()['label_count']==3 and calibration.json()['mean_absolute_error']==0
        assert len(client.get('/v1/evaluations/human-labels',headers=headers['reviewer'],
            params={'dataset_id':dataset.json()['dataset_id']}).json())==3
        assert any(x['calibration_id']==calibration.json()['calibration_id'] for x in
            client.get('/v1/evaluations/calibrations',headers=headers['reviewer']).json())

        gate=client.post('/v1/evaluations/release-gates',headers=headers['developer'],json={
            'idempotency_key':'stage4-gate-'+marker,
            'experiment_ids':[item['experiment_id'] for item in reports],
            'calibration_id':calibration.json()['calibration_id'],'min_mean_pass_rate':0.9,
            'max_pass_rate_stddev':0.05,'max_regression':0.02,'require_held_out':True})
        assert gate.status_code==201 and gate.json()['passed'],gate.text
        assert all(gate.json()['checks'].values())
        assert any(x['release_gate_id']==gate.json()['release_gate_id'] for x in
            client.get('/v1/evaluations/release-gates',headers=headers['reviewer']).json())
        gate_file=ROOT/'.local'/f'stage4-release-gate-{marker}.json'; gate_file.write_text(json.dumps(gate.json()),encoding='utf-8')
        checked=subprocess.run([sys.executable,str(ROOT/'scripts'/'release_gate.py'),str(gate_file)],capture_output=True,text=True)
        assert checked.returncode==0,checked.stdout+checked.stderr

        online_dataset=client.post('/v1/evaluations/datasets',headers=headers['developer'],json={
            'slug':'stage4-online-'+marker,'version':1,'cases':[{'case_key':'online-case','category':'online',
                'split':'validation','expected':{'semantic_judge':rubric}}]})
        assert online_dataset.status_code==201,online_dataset.text
        policy=client.put('/v1/evaluations/online-policy',headers=headers['admin'],json={
            'dataset_id':online_dataset.json()['dataset_id'],'case_key':'online-case','sample_rate':'1.00000',
            'daily_limit':10,'enabled':True})
        assert policy.status_code==200,policy.text
        assert client.get('/v1/evaluations/online-policy',headers=headers['worker']).json()['case_key']=='online-case'
        sampled=client.post(f'/v1/runs/{runs[0]}/evaluation-sample',headers=headers['worker'],json={})
        assert sampled.status_code==200 and sampled.json()['selected'] and sampled.json()['experiment_id'],sampled.text
        replay=client.post(f'/v1/runs/{runs[0]}/evaluation-sample',headers=headers['worker'],json={})
        assert replay.json()['experiment_id']==sampled.json()['experiment_id'] and replay.json()['reason']=='stable_replay'
        assert client.post('/v1/evaluations/human-labels',headers=headers['worker'],json={
            'dataset_id':dataset.json()['dataset_id'],'case_key':'billing-case','run_id':runs[0],
            'score':'0.9','label':'pass'}).status_code==403
    print('Stage 4 acceptance passed: held-out coverage, semantic judging, calibration, uncertainty, release gate and online sampling.')


if __name__=='__main__': main()
