"""Real PostgreSQL/API acceptance for Stage 5 sessions and product operations."""
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import dev
import native_postgres
from sentinel.config import Settings
from sentinel.main import create_app
from sentinel.evaluations import digest


def main():
    dev.setup(); config=dev.load_config(); marker=uuid4().hex
    app=create_app(Settings(database_url=native_postgres.dsn(),auth_pepper=config['auth_pepper'],
        booking_service_url='http://127.0.0.1:8002',credential_encryption_key=config['credential_encryption_key']))
    headers={role:{'X-API-Key':token} for role,token in config['keys'].items()}
    with TestClient(app) as client:
        preflight=client.options('/v1/sessions/login',headers={'Origin':'http://127.0.0.1:3000',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        assert preflight.status_code==200
        assert preflight.headers.get('access-control-allow-credentials')=='true'
        profile=client.put('/v1/onboarding/organization',headers=headers['admin'],json={
            'slug':'stage5-'+marker[:12],'display_name':'Stage 5 organization'})
        assert profile.status_code==200,profile.text
        invitation=client.post('/v1/onboarding/invitations',headers=headers['admin'],json={
            'handle':'developer.'+marker[:8],'role':'developer','expires_in_hours':2})
        assert invitation.status_code==201 and invitation.json()['token'].startswith('sni_'),invitation.text
        with app.state.database.connect() as connection:
            stored=str(connection.execute('SELECT * FROM sentinel_member_invitations WHERE invitation_id=%s',(invitation.json()['invitation_id'],)).fetchone())
            assert invitation.json()['token'] not in stored

        session=TestClient(app)
        accepted=session.post('/v1/onboarding/accept',json={'token':invitation.json()['token'],
            'display_name':'Stage Five Developer','password':'StrongPassword123'})
        assert accepted.status_code==201,accepted.text
        assert accepted.cookies.get('sentinel_session') and accepted.cookies.get('sentinel_csrf')
        who=session.get('/v1/me'); assert who.status_code==200 and who.json()['auth_kind']=='session'
        assert who.json()['member']['display_name']=='Stage Five Developer'
        denied=session.post('/v1/agents',json={'slug':'denied','display_name':'Denied'})
        assert denied.status_code==403
        csrf=session.cookies.get('sentinel_csrf'); session_headers={'X-CSRF-Token':csrf}
        agent=session.post('/v1/agents',headers=session_headers,json={
            'slug':'session_'+marker,'display_name':'Session-created agent'})
        assert agent.status_code==201,agent.text
        assert session.get('/v1/onboarding/members').status_code==403
        listed=client.get('/v1/access/keys',headers=headers['admin']).json()
        assert all(item['key_prefix'].startswith('snt_') for item in listed)
        logged_out=session.post('/v1/sessions/logout',headers=session_headers,json={})
        assert logged_out.status_code==200 and session.get('/v1/me').status_code==401
        login=session.post('/v1/sessions/login',json={'organization_slug':'stage5-'+marker[:12],
            'handle':'developer.'+marker[:8],'password':'StrongPassword123'})
        assert login.status_code==200 and session.get('/v1/me').status_code==200

        identity=client.get('/v1/me',headers=headers['admin']).json(); org=identity['organization_id']
        with app.state.database.connect() as connection:
            actor=connection.execute("SELECT api_key_id FROM sentinel_api_keys WHERE organization_id=%s AND role='admin' AND key_kind='service' ORDER BY created_at LIMIT 1",(org,)).fetchone()['api_key_id']
            dataset=connection.execute('SELECT dataset_id FROM sentinel_evaluation_datasets WHERE organization_id=%s ORDER BY created_at LIMIT 1',(org,)).fetchone()
            if dataset is None:
                dataset_id=uuid4()
                definition={'slug':'stage5-fixture','version':1,'cases':[{'case_key':'gate','expected':{'run_status':'succeeded'}}]}
                connection.execute("INSERT INTO sentinel_evaluation_datasets(dataset_id,organization_id,slug,version,definition,content_hash,created_by_key_id) VALUES (%s,%s,%s,1,%s,%s,%s)",(dataset_id,org,'stage5-fixture-'+marker,Jsonb(definition),digest(definition),actor))
            else: dataset_id=dataset['dataset_id']
            experiment=connection.execute('SELECT experiment_id FROM sentinel_evaluation_experiments WHERE organization_id=%s ORDER BY created_at LIMIT 1',(org,)).fetchone()
            if experiment is None:
                experiment_id=uuid4(); report={'experiment_id':str(experiment_id),'dataset_id':str(dataset_id),'evaluator_version':'agent_rules_v2','cases':[{'case_key':'gate','checks':[{'rule':'run_status','expected':'succeeded','actual':'succeeded','passed':True}],'passed':True}],'passed_cases':1,'total_cases':1,'pass_rate':1.0,'gate':{'min_pass_rate':1.0,'passed':True}}
                connection.execute("INSERT INTO sentinel_evaluation_experiments(experiment_id,organization_id,dataset_id,idempotency_key,request_hash,report,created_by_key_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",(experiment_id,org,dataset_id,'stage5-exp-'+marker,'a'*64,Jsonb(report),actor))
            else: experiment_id=experiment['experiment_id']
            gate_ids=[]
            for passed in (False,True):
                gate_id=uuid4(); gate_ids.append(gate_id); report={'release_gate_id':str(gate_id),'dataset_id':str(dataset_id),'checks':{'mean_pass_rate':passed,'pass_rate_stability':True,'held_out':True,'calibration':True,'regression':True},'passed':passed}
                connection.execute("INSERT INTO sentinel_evaluation_release_gates(release_gate_id,organization_id,idempotency_key,request_hash,report,created_by_key_id) VALUES (%s,%s,%s,%s,%s,%s)",(gate_id,org,f'stage5-gate-{passed}-{marker}',digest(report),Jsonb(report),actor))

        policy=client.put('/v1/alerts/policy',headers=headers['admin'],json={
            'telemetry_incomplete':False,'release_gate_failed':True,'failed_run_threshold':1000})
        assert policy.status_code==200,policy.text
        assert client.post('/v1/alerts/evaluate',headers=headers['worker'],json={}).status_code==200
        alerts=client.get('/v1/alerts',headers=headers['reviewer']).json()
        release_alert=next(item for item in alerts if item['reference_id']==str(gate_ids[0]))
        acknowledged=client.post(f"/v1/alerts/{release_alert['alert_id']}/acknowledge",headers=headers['reviewer'],json={})
        assert acknowledged.json()['status']=='acknowledged'

        environment=client.post('/v1/deployments/environments',headers=headers['admin'],json={
            'slug':'local-pilot-'+marker[:8],'display_name':'Local pilot'})
        assert environment.status_code==201,environment.text
        base={'environment_id':environment.json()['environment_id'],'artifact_digest':'b'*64,'version':'v-'+marker[:8]}
        blocked=client.post('/v1/deployments',headers=headers['developer'],json={**base,'release_gate_id':str(gate_ids[0])})
        assert blocked.status_code==409
        deployment=client.post('/v1/deployments',headers=headers['developer'],json={**base,'release_gate_id':str(gate_ids[1])})
        assert deployment.status_code==201 and deployment.json()['status']=='approved',deployment.text
        deployed=client.post(f"/v1/deployments/{deployment.json()['deployment_id']}/status",headers=headers['worker'],json={'status':'deployed'})
        assert deployed.status_code==200 and deployed.json()['status']=='deployed'

        campaign=client.post('/v1/labs/campaigns',headers=headers['developer'],json={
            'campaign_type':'security','profile':'boundary'})
        assert campaign.status_code==201
        claim=client.post('/v1/labs/campaigns/claim',headers=headers['worker'],json={})
        assert claim.status_code==200 and claim.json()['campaign_id']==campaign.json()['campaign_id']
        complete=client.post(f"/v1/labs/campaigns/{claim.json()['campaign_id']}/complete",headers=headers['worker'],json={
            'passed':True,'checks_run':12,'checks_failed':0,'duration_ms':50})
        assert complete.status_code==200 and complete.json()['status']=='passed'
        view=client.get('/v1/labs/campaigns',headers=headers['reviewer']).json()
        assert any(item['campaign_id']==campaign.json()['campaign_id'] and item['report_hash'] for item in view)
    print('Stage 5 acceptance passed: sessions, invitations, CSRF, alerts, deployment gates and lab campaigns.')


if __name__=='__main__': main()
