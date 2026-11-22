"""Operational alerts, deployment gates and bounded lab campaigns."""
from __future__ import annotations

from datetime import datetime,timezone
from typing import Literal
from uuid import UUID,uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel,ConfigDict,Field,model_validator

from .evaluations import digest
from .security import require_roles


class AlertPolicyUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    telemetry_incomplete: bool=True
    release_gate_failed: bool=True
    failed_run_threshold: int=Field(default=3,ge=1,le=1000)


class EnvironmentCreate(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    slug: str=Field(pattern=r'^[a-z][a-z0-9_-]{2,49}$')
    display_name: str=Field(min_length=2,max_length=100)


class DeploymentCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    environment_id: UUID
    release_gate_id: UUID
    artifact_digest: str=Field(pattern=r'^[0-9a-f]{64}$')
    version: str=Field(pattern=r'^[a-zA-Z0-9_.-]{1,80}$')


class DeploymentStatusUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: Literal['deployed','failed','rolled_back']


class LabCampaignCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    campaign_type: Literal['fault','security']
    profile: Literal['boundary','recovery','full']


class LabCampaignComplete(BaseModel):
    model_config=ConfigDict(extra='forbid')
    passed: bool
    checks_run: int=Field(ge=1,le=100000)
    checks_failed: int=Field(ge=0,le=100000)
    duration_ms: int=Field(ge=0,le=86400000)

    @model_validator(mode='after')
    def consistent(self):
        if self.checks_failed>self.checks_run or self.passed!=(self.checks_failed==0):
            raise ValueError('Campaign verdict contradicts check counts.')
        return self


def set_alert_policy(database,principal,body):
    require_roles('admin')(principal)
    with database.connect() as connection:
        return connection.execute("""INSERT INTO sentinel_alert_policies
          (organization_id,telemetry_incomplete,release_gate_failed,failed_run_threshold,updated_by_key_id)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT(organization_id) DO UPDATE SET
          telemetry_incomplete=excluded.telemetry_incomplete,
          release_gate_failed=excluded.release_gate_failed,
          failed_run_threshold=excluded.failed_run_threshold,
          updated_by_key_id=excluded.updated_by_key_id,updated_at=now() RETURNING *""",
          (principal.organization_id,body.telemetry_incomplete,body.release_gate_failed,
           body.failed_run_threshold,principal.api_key_id)).fetchone()


def get_alert_policy(database,principal):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection:
        row=connection.execute('SELECT telemetry_incomplete,release_gate_failed,failed_run_threshold,updated_at FROM sentinel_alert_policies WHERE organization_id=%s',(principal.organization_id,)).fetchone()
    return row or {'telemetry_incomplete':True,'release_gate_failed':True,'failed_run_threshold':3,'updated_at':None}


def _alert(connection,org,kind,severity,reference,summary):
    connection.execute("""INSERT INTO sentinel_alerts
      (alert_id,organization_id,alert_type,severity,reference_id,summary)
      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(organization_id,alert_type,reference_id) DO NOTHING""",
      (uuid4(),org,kind,severity,reference,Jsonb(summary)))


def evaluate_alerts(database,principal):
    require_roles('admin','developer','worker')(principal)
    with database.connect() as connection:
        policy=connection.execute('SELECT * FROM sentinel_alert_policies WHERE organization_id=%s',(principal.organization_id,)).fetchone()
        if policy is None:
            policy={'telemetry_incomplete':True,'release_gate_failed':True,'failed_run_threshold':3}
        created_before=connection.execute('SELECT count(*) AS n FROM sentinel_alerts WHERE organization_id=%s',(principal.organization_id,)).fetchone()['n']
        if policy['release_gate_failed']:
            for row in connection.execute("SELECT release_gate_id::text,report FROM sentinel_evaluation_release_gates WHERE organization_id=%s AND NOT (report->>'passed')::boolean",(principal.organization_id,)).fetchall():
                _alert(connection,principal.organization_id,'release_gate_failed','critical',row['release_gate_id'],
                       {'passed':False,'failed_check_count':sum(not value for value in row['report']['checks'].values())})
        failed=connection.execute("SELECT count(*) AS n FROM sentinel_runs WHERE organization_id=%s AND status='failed' AND completed_at>=now()-interval '1 hour'",(principal.organization_id,)).fetchone()['n']
        if failed>=policy['failed_run_threshold']:
            bucket=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
            _alert(connection,principal.organization_id,'failed_runs','critical',bucket,
                   {'window_minutes':60,'failed_run_count':failed,'threshold':policy['failed_run_threshold']})
        if policy['telemetry_incomplete']:
            required=connection.execute('SELECT required_signals,require_token_usage,require_cost FROM sentinel_telemetry_policies WHERE organization_id=%s',(principal.organization_id,)).fetchone()
            if required:
                runs=connection.execute("SELECT run_id::text FROM sentinel_runs WHERE organization_id=%s AND completed_at>=now()-interval '24 hours' ORDER BY completed_at DESC LIMIT 100",(principal.organization_id,)).fetchall()
                for run in runs:
                    signals={row['signal_type'] for row in connection.execute('SELECT DISTINCT signal_type FROM sentinel_telemetry_batches WHERE organization_id=%s AND run_id=%s',(principal.organization_id,run['run_id'])).fetchall()}
                    trace=connection.execute("SELECT EXISTS(SELECT 1 FROM sentinel_pending_otlp_traces WHERE organization_id=%s AND run_id=%s) OR EXISTS(SELECT 1 FROM sentinel_external_traces WHERE organization_id=%s AND run_id=%s) AS present",(principal.organization_id,run['run_id'],principal.organization_id,run['run_id'])).fetchone()['present']
                    if trace: signals.add('traces')
                    gaps=sorted(set(required['required_signals'])-signals)
                    if gaps: _alert(connection,principal.organization_id,'telemetry_incomplete','warning',run['run_id'],{'missing_signals':gaps})
        created_after=connection.execute('SELECT count(*) AS n FROM sentinel_alerts WHERE organization_id=%s',(principal.organization_id,)).fetchone()['n']
    return {'new_alerts':created_after-created_before}


def list_alerts(database,principal,status=None):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection:
        if status is None:
            return connection.execute("""SELECT alert_id,alert_type,severity,reference_id,summary,status,
              acknowledged_at,created_at FROM sentinel_alerts WHERE organization_id=%s
              ORDER BY created_at DESC LIMIT 200""",(principal.organization_id,)).fetchall()
        return connection.execute("""SELECT alert_id,alert_type,severity,reference_id,summary,status,
          acknowledged_at,created_at FROM sentinel_alerts WHERE organization_id=%s
          AND status=%s ORDER BY created_at DESC LIMIT 200""",
          (principal.organization_id,status)).fetchall()


def acknowledge_alert(database,principal,alert_id):
    require_roles('admin','reviewer')(principal)
    with database.connect() as connection:
        row=connection.execute("""UPDATE sentinel_alerts SET status='acknowledged',
          acknowledged_by_key_id=%s,acknowledged_at=now() WHERE alert_id=%s AND organization_id=%s
          RETURNING alert_id,alert_type,severity,reference_id,summary,status,acknowledged_at,created_at""",
          (principal.api_key_id,alert_id,principal.organization_id)).fetchone()
    if row is None: raise HTTPException(404,'Alert not found.')
    return row


def create_environment(database,principal,body):
    require_roles('admin')(principal)
    with database.connect() as connection:
        row=connection.execute("""INSERT INTO sentinel_deployment_environments
          (environment_id,organization_id,slug,display_name,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
          (uuid4(),principal.organization_id,body.slug,body.display_name,principal.api_key_id)).fetchone()
        if row is None: row=connection.execute('SELECT * FROM sentinel_deployment_environments WHERE organization_id=%s AND slug=%s',(principal.organization_id,body.slug)).fetchone()
    return row


def list_environments(database,principal):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection:
        return connection.execute('SELECT environment_id,slug,display_name,created_at FROM sentinel_deployment_environments WHERE organization_id=%s ORDER BY created_at',(principal.organization_id,)).fetchall()


def create_deployment(database,principal,body):
    require_roles('admin','developer')(principal)
    with database.connect() as connection:
        gate=connection.execute('SELECT report FROM sentinel_evaluation_release_gates WHERE release_gate_id=%s AND organization_id=%s',(body.release_gate_id,principal.organization_id)).fetchone()
        if gate is None: raise HTTPException(404,'Release gate not found.')
        if not gate['report']['passed']: raise HTTPException(409,'Deployment requires a passed release gate.')
        environment=connection.execute('SELECT 1 FROM sentinel_deployment_environments WHERE environment_id=%s AND organization_id=%s',(body.environment_id,principal.organization_id)).fetchone()
        if environment is None: raise HTTPException(404,'Deployment environment not found.')
        row=connection.execute("""INSERT INTO sentinel_deployment_records
          (deployment_id,organization_id,environment_id,release_gate_id,artifact_digest,version,status,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,'approved',%s) ON CONFLICT DO NOTHING RETURNING *""",
          (uuid4(),principal.organization_id,body.environment_id,body.release_gate_id,
           body.artifact_digest,body.version,principal.api_key_id)).fetchone()
        if row is None:
            row=connection.execute('SELECT * FROM sentinel_deployment_records WHERE organization_id=%s AND environment_id=%s AND version=%s',(principal.organization_id,body.environment_id,body.version)).fetchone()
            if row['artifact_digest']!=body.artifact_digest or row['release_gate_id']!=body.release_gate_id:
                raise HTTPException(409,'Deployment version already represents another artifact or gate.')
    return row


def update_deployment(database,principal,deployment_id,body):
    require_roles('admin','worker')(principal)
    with database.connect() as connection:
        row=connection.execute('SELECT * FROM sentinel_deployment_records WHERE deployment_id=%s AND organization_id=%s FOR UPDATE',(deployment_id,principal.organization_id)).fetchone()
        if row is None: raise HTTPException(404,'Deployment not found.')
        allowed=(row['status']=='approved' and body.status in ('deployed','failed')) or (row['status']=='deployed' and body.status=='rolled_back')
        if not allowed: raise HTTPException(409,'Invalid deployment status transition.')
        row=connection.execute("""UPDATE sentinel_deployment_records SET status=%s,
          deployed_at=CASE WHEN %s='deployed' THEN now() ELSE deployed_at END
          WHERE deployment_id=%s RETURNING *""",(body.status,body.status,deployment_id)).fetchone()
    return row


def list_deployments(database,principal):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection:
        return connection.execute("""SELECT deployment_id,environment_id,release_gate_id,
          artifact_digest,version,status,deployed_at,created_at FROM sentinel_deployment_records
          WHERE organization_id=%s ORDER BY created_at DESC LIMIT 200""",(principal.organization_id,)).fetchall()


def create_campaign(database,principal,body):
    require_roles('admin','developer')(principal)
    with database.connect() as connection:
        return connection.execute("""INSERT INTO sentinel_lab_campaigns
          (campaign_id,organization_id,campaign_type,profile,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s) RETURNING *""",(uuid4(),principal.organization_id,
          body.campaign_type,body.profile,principal.api_key_id)).fetchone()


def claim_campaign(database,principal):
    require_roles('worker')(principal)
    with database.connect() as connection:
        row=connection.execute("""SELECT * FROM sentinel_lab_campaigns WHERE organization_id=%s
          AND status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""",
          (principal.organization_id,)).fetchone()
        if row is None: return None
        return connection.execute("""UPDATE sentinel_lab_campaigns SET status='running',
          claimed_by_key_id=%s,started_at=now() WHERE campaign_id=%s RETURNING *""",
          (principal.api_key_id,row['campaign_id'])).fetchone()


def complete_campaign(database,principal,campaign_id,body):
    require_roles('worker')(principal)
    report={'passed':body.passed,'checks_run':body.checks_run,
            'checks_failed':body.checks_failed,'duration_ms':body.duration_ms}
    report_hash=digest(report)
    with database.connect() as connection:
        row=connection.execute("""UPDATE sentinel_lab_campaigns SET status=%s,report=%s,
          report_hash=%s,completed_at=now() WHERE campaign_id=%s AND organization_id=%s
          AND status='running' AND claimed_by_key_id=%s RETURNING *""",
          ('passed' if body.passed else 'failed',Jsonb(report),report_hash,campaign_id,
           principal.organization_id,principal.api_key_id)).fetchone()
    if row is None: raise HTTPException(409,'Campaign is not claimed by this worker.')
    return row


def list_campaigns(database,principal):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection:
        return connection.execute("""SELECT campaign_id,campaign_type,profile,status,report,
          report_hash,created_at,started_at,completed_at FROM sentinel_lab_campaigns
          WHERE organization_id=%s ORDER BY created_at DESC LIMIT 100""",(principal.organization_id,)).fetchall()
