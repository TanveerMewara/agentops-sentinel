"""Human calibration, repeated analysis, release decisions and online sampling."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import math
import statistics
from uuid import UUID,uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel,ConfigDict,Field,model_validator

from .evaluations import ExperimentCreate,create_experiment,digest
from .security import require_roles


class HumanLabelCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id: UUID
    case_key: str=Field(pattern=r'^[a-z][a-z0-9_-]{2,79}$')
    run_id: UUID
    score: Decimal=Field(ge=0,le=1,max_digits=5,decimal_places=4)
    label: str=Field(pattern=r'^(pass|fail)$')

    @model_validator(mode='after')
    def consistent(self):
        if (self.label=='pass') != (self.score>=Decimal('0.5')):
            raise ValueError('Human label must agree with the score threshold.')
        return self


class CalibrationCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    experiment_id: UUID
    min_labels: int=Field(default=3,ge=3,le=1000)
    max_mean_absolute_error: float=Field(default=0.2,ge=0,le=1,allow_inf_nan=False)
    min_label_agreement: float=Field(default=0.8,ge=0,le=1,allow_inf_nan=False)


class ExperimentAnalysisCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    experiment_ids: list[UUID]=Field(min_length=2,max_length=50)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.experiment_ids))!=len(self.experiment_ids): raise ValueError('Experiment IDs must be unique.')
        return self


class ReleaseGateCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    idempotency_key: str=Field(min_length=8,max_length=200)
    experiment_ids: list[UUID]=Field(min_length=2,max_length=50)
    baseline_experiment_ids: list[UUID]=Field(default_factory=list,max_length=50)
    calibration_id: UUID | None=None
    min_mean_pass_rate: float=Field(default=0.9,ge=0,le=1,allow_inf_nan=False)
    max_pass_rate_stddev: float=Field(default=0.05,ge=0,le=1,allow_inf_nan=False)
    max_regression: float=Field(default=0.02,ge=0,le=1,allow_inf_nan=False)
    require_held_out: bool=True

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.experiment_ids))!=len(self.experiment_ids): raise ValueError('Candidate IDs must be unique.')
        if len(set(self.baseline_experiment_ids))!=len(self.baseline_experiment_ids): raise ValueError('Baseline IDs must be unique.')
        return self


class SamplingPolicyUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dataset_id: UUID
    case_key: str=Field(pattern=r'^[a-z][a-z0-9_-]{2,79}$')
    sample_rate: Decimal=Field(ge=0,le=1,max_digits=6,decimal_places=5)
    daily_limit: int=Field(default=100,ge=1,le=10000)
    enabled: bool=True


def create_human_label(database,principal,body):
    require_roles('admin','reviewer')(principal)
    with database.connect() as connection:
        dataset=connection.execute('SELECT definition FROM sentinel_evaluation_datasets WHERE dataset_id=%s AND organization_id=%s',(body.dataset_id,principal.organization_id)).fetchone()
        if dataset is None: raise HTTPException(404,'Evaluation dataset not found.')
        if body.case_key not in {case['case_key'] for case in dataset['definition']['cases']}:
            raise HTTPException(422,'Case is not part of this dataset version.')
        run=connection.execute('SELECT status FROM sentinel_runs WHERE run_id=%s AND organization_id=%s',(body.run_id,principal.organization_id)).fetchone()
        if run is None: raise HTTPException(404,'Evaluation run not found.')
        if run['status'] in ('queued','running'): raise HTTPException(409,'Human labels require a terminal run.')
        row=connection.execute("""INSERT INTO sentinel_evaluation_human_labels
          (human_label_id,organization_id,dataset_id,case_key,run_id,score,label,reviewer_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
          (uuid4(),principal.organization_id,body.dataset_id,body.case_key,body.run_id,body.score,body.label,principal.api_key_id)).fetchone()
        if row is None:
            row=connection.execute("""SELECT * FROM sentinel_evaluation_human_labels WHERE
              organization_id=%s AND dataset_id=%s AND case_key=%s AND run_id=%s AND reviewer_key_id=%s""",
              (principal.organization_id,body.dataset_id,body.case_key,body.run_id,principal.api_key_id)).fetchone()
            if row['score']!=body.score or row['label']!=body.label: raise HTTPException(409,'This reviewer already submitted a different immutable label.')
            return _label_view(row),False
    return _label_view(row),True


def _label_view(row):
    return {key:row[key] for key in ('human_label_id','dataset_id','case_key','run_id','score','label','created_at')}


def list_human_labels(database,principal,dataset_id):
    require_roles('admin','reviewer')(principal)
    with database.connect() as connection:
        rows=connection.execute("""SELECT * FROM sentinel_evaluation_human_labels
          WHERE organization_id=%s AND dataset_id=%s ORDER BY created_at""",
          (principal.organization_id,dataset_id)).fetchall()
    return [_label_view(row) for row in rows]


def create_calibration(database,principal,body):
    require_roles('admin','reviewer')(principal)
    with database.connect() as connection:
        experiment=connection.execute('SELECT dataset_id,report FROM sentinel_evaluation_experiments WHERE experiment_id=%s AND organization_id=%s',(body.experiment_id,principal.organization_id)).fetchone()
        if experiment is None: raise HTTPException(404,'Evaluation experiment not found.')
        semantic={ (case['case_key'],case['run_id']):check for case in experiment['report']['cases']
            for check in case['checks'] if check['rule']=='semantic_judge'}
        if not semantic: raise HTTPException(409,'Calibration requires a semantic-judge experiment.')
        labels=connection.execute('SELECT case_key,run_id::text,score,label FROM sentinel_evaluation_human_labels WHERE dataset_id=%s AND organization_id=%s',(experiment['dataset_id'],principal.organization_id)).fetchall()
        matched=[(semantic[(row['case_key'],row['run_id'])],row) for row in labels if (row['case_key'],row['run_id']) in semantic]
        if len(matched)<body.min_labels: raise HTTPException(409,'Not enough matching human labels for calibration.')
        config_hash=digest({'request':body.model_dump(mode='json'),'labels':sorted(
          [{'case_key':row['case_key'],'run_id':row['run_id'],'score':str(row['score']),'label':row['label']}
           for _,row in matched],key=lambda item:(item['case_key'],item['run_id'],item['score'],item['label']))})
        errors=[abs(float(row['score'])-float(check['score'])) for check,row in matched]
        agreements=[(row['label']=='pass')==(float(check['score'])>=0.5) for check,row in matched]
        mae=sum(errors)/len(errors); agreement=sum(agreements)/len(agreements)
        judge_hashes=sorted({check['judge_config_hash'] for check,_ in matched})
        passed=mae<=body.max_mean_absolute_error and agreement>=body.min_label_agreement
        report={'calibration_id':str(uuid4()),'experiment_id':str(body.experiment_id),
          'dataset_id':str(experiment['dataset_id']),'label_count':len(matched),
          'mean_absolute_error':round(mae,6),'label_agreement':round(agreement,6),
          'judge_config_hashes':judge_hashes,'thresholds':{
            'min_labels':body.min_labels,'max_mean_absolute_error':body.max_mean_absolute_error,
            'min_label_agreement':body.min_label_agreement},'passed':passed}
        existing=connection.execute('SELECT report FROM sentinel_evaluation_calibrations WHERE organization_id=%s AND config_hash=%s',(principal.organization_id,config_hash)).fetchone()
        if existing: return existing['report'],False
        connection.execute("""INSERT INTO sentinel_evaluation_calibrations
          (calibration_id,organization_id,dataset_id,experiment_id,config_hash,report,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s)""",(report['calibration_id'],principal.organization_id,
          experiment['dataset_id'],body.experiment_id,config_hash,Jsonb(report),principal.api_key_id))
    return report,True


def list_calibrations(database,principal):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection:
        return [row['report'] for row in connection.execute(
          'SELECT report FROM sentinel_evaluation_calibrations WHERE organization_id=%s ORDER BY created_at DESC LIMIT 100',
          (principal.organization_id,)).fetchall()]


def _load_reports(connection,organization_id,ids):
    rows=connection.execute('SELECT experiment_id::text,report FROM sentinel_evaluation_experiments WHERE organization_id=%s AND experiment_id=ANY(%s)',(organization_id,ids)).fetchall()
    reports={row['experiment_id']:row['report'] for row in rows}
    if len(reports)!=len(ids): raise HTTPException(404,'One or more experiments were not found.')
    return [reports[str(item)] for item in ids]


def analyze_reports(reports):
    dataset_ids={item['dataset_id'] for item in reports}; versions={item['evaluator_version'] for item in reports}
    if len(dataset_ids)!=1 or len(versions)!=1: raise HTTPException(409,'Analysis requires one dataset and evaluator version.')
    rates=[float(item['pass_rate']) for item in reports]; mean=sum(rates)/len(rates); sd=statistics.pstdev(rates)
    margin=1.96*sd/math.sqrt(len(rates))
    categories=sorted({case.get('category','general') for report in reports for case in report['cases']})
    return {'dataset_id':next(iter(dataset_ids)),'evaluator_version':next(iter(versions)),
      'experiment_count':len(reports),'mean_pass_rate':round(mean,6),'pass_rate_stddev':round(sd,6),
      'confidence_interval_95':[round(max(0,mean-margin),6),round(min(1,mean+margin),6)],
      'min_pass_rate':min(rates),'max_pass_rate':max(rates),
      'held_out':all(item.get('dataset_profile',{}).get('held_out',False) for item in reports),
      'categories':{category:{'cases':sum(case.get('category','general')==category for report in reports for case in report['cases']),
        'passed':sum(case.get('category','general')==category and case['passed'] for report in reports for case in report['cases'])}
        for category in categories},'variants':[item.get('variant') for item in reports]}


def analyze_experiments(database,principal,body):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection: reports=_load_reports(connection,principal.organization_id,body.experiment_ids)
    return analyze_reports(reports)


def create_release_gate(database,principal,body):
    require_roles('admin','developer','reviewer')(principal)
    request_hash=digest(body.model_dump(mode='json'))
    with database.connect() as connection:
        previous=connection.execute('SELECT request_hash,report FROM sentinel_evaluation_release_gates WHERE organization_id=%s AND idempotency_key=%s',(principal.organization_id,body.idempotency_key)).fetchone()
        if previous:
            if previous['request_hash']!=request_hash: raise HTTPException(409,'Release gate key already represents another request.')
            return previous['report'],False
        candidate_reports=_load_reports(connection,principal.organization_id,body.experiment_ids)
        analysis=analyze_reports(candidate_reports)
        baseline=None
        if body.baseline_experiment_ids:
            baseline=analyze_reports(_load_reports(connection,principal.organization_id,body.baseline_experiment_ids))
            if baseline['dataset_id']!=analysis['dataset_id']: raise HTTPException(409,'Baseline must use the candidate dataset version.')
        semantic=analysis['evaluator_version']=='agent_rules_v5'; calibration=None
        if body.calibration_id:
            row=connection.execute('SELECT report FROM sentinel_evaluation_calibrations WHERE calibration_id=%s AND organization_id=%s',(body.calibration_id,principal.organization_id)).fetchone()
            if row is None: raise HTTPException(404,'Calibration not found.')
            calibration=row['report']
            if calibration['dataset_id']!=analysis['dataset_id']: raise HTTPException(409,'Calibration uses another dataset version.')
        checks={'mean_pass_rate':analysis['mean_pass_rate']>=body.min_mean_pass_rate,
          'pass_rate_stability':analysis['pass_rate_stddev']<=body.max_pass_rate_stddev,
          'held_out':(not body.require_held_out or analysis['held_out']),
          'calibration':(not semantic or bool(calibration and calibration['passed'])),
          'regression':(baseline is None or analysis['mean_pass_rate']>=baseline['mean_pass_rate']-body.max_regression)}
        report={'release_gate_id':str(uuid4()),'dataset_id':analysis['dataset_id'],
          'candidate_analysis':analysis,'baseline_analysis':baseline,'calibration_id':str(body.calibration_id) if body.calibration_id else None,
          'criteria':{'min_mean_pass_rate':body.min_mean_pass_rate,'max_pass_rate_stddev':body.max_pass_rate_stddev,
            'max_regression':body.max_regression,'require_held_out':body.require_held_out},
          'checks':checks,'passed':all(checks.values())}
        connection.execute("""INSERT INTO sentinel_evaluation_release_gates
          (release_gate_id,organization_id,idempotency_key,request_hash,report,created_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s)""",(report['release_gate_id'],principal.organization_id,
          body.idempotency_key,request_hash,Jsonb(report),principal.api_key_id))
    return report,True


def list_release_gates(database,principal):
    require_roles('admin','developer','reviewer')(principal)
    with database.connect() as connection:
        return [row['report'] for row in connection.execute(
          'SELECT report FROM sentinel_evaluation_release_gates WHERE organization_id=%s ORDER BY created_at DESC LIMIT 100',
          (principal.organization_id,)).fetchall()]


def set_sampling_policy(database,principal,body):
    require_roles('admin')(principal)
    with database.connect() as connection:
        dataset=connection.execute('SELECT definition FROM sentinel_evaluation_datasets WHERE dataset_id=%s AND organization_id=%s',(body.dataset_id,principal.organization_id)).fetchone()
        if dataset is None: raise HTTPException(404,'Evaluation dataset not found.')
        cases={item['case_key'] for item in dataset['definition']['cases']}
        if cases!={body.case_key}: raise HTTPException(422,'Online sampling requires a single-case dataset matching case_key.')
        return connection.execute("""INSERT INTO sentinel_evaluation_sampling_policies
          (organization_id,dataset_id,case_key,sample_rate,daily_limit,enabled,updated_by_key_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (organization_id) DO UPDATE SET
          dataset_id=excluded.dataset_id,case_key=excluded.case_key,sample_rate=excluded.sample_rate,
          daily_limit=excluded.daily_limit,enabled=excluded.enabled,updated_by_key_id=excluded.updated_by_key_id,
          updated_at=now() RETURNING *""",(principal.organization_id,body.dataset_id,body.case_key,
          body.sample_rate,body.daily_limit,body.enabled,principal.api_key_id)).fetchone()


def get_sampling_policy(database,principal):
    require_roles('admin','developer','reviewer','worker')(principal)
    with database.connect() as connection:
        row=connection.execute("""SELECT dataset_id,case_key,sample_rate,daily_limit,enabled,updated_at
          FROM sentinel_evaluation_sampling_policies WHERE organization_id=%s""",
          (principal.organization_id,)).fetchone()
    return row


def sample_run(database,principal,run_id,semantic_judge=None):
    require_roles('admin','developer','worker')(principal)
    with database.connect() as connection:
        connection.execute('SELECT 1 FROM sentinel_organizations WHERE organization_id=%s FOR UPDATE',
                           (principal.organization_id,)).fetchone()
        run=connection.execute('SELECT status FROM sentinel_runs WHERE run_id=%s AND organization_id=%s',(run_id,principal.organization_id)).fetchone()
        if run is None: raise HTTPException(404,'Run not found.')
        if run['status'] in ('queued','running'): raise HTTPException(409,'Online sampling requires a terminal run.')
        policy=connection.execute('SELECT * FROM sentinel_evaluation_sampling_policies WHERE organization_id=%s',(principal.organization_id,)).fetchone()
        if policy is None or not policy['enabled']: return {'selected':False,'reason':'disabled','experiment_id':None}
        existing=connection.execute('SELECT * FROM sentinel_evaluation_online_samples WHERE organization_id=%s AND run_id=%s',(principal.organization_id,run_id)).fetchone()
        if existing and (not existing['selected'] or existing['experiment_id']):
            return {'selected':existing['selected'],'reason':'stable_replay','experiment_id':str(existing['experiment_id']) if existing['experiment_id'] else None}
        selected_today=connection.execute("SELECT count(*) AS n FROM sentinel_evaluation_online_samples WHERE organization_id=%s AND selected AND sampled_at>=date_trunc('day',now())",(principal.organization_id,)).fetchone()['n']
        value=int(hashlib.sha256(f'{principal.organization_id}:{run_id}:{policy["dataset_id"]}'.encode()).hexdigest()[:16],16)/float(16**16)
        selected=selected_today<policy['daily_limit'] and value<float(policy['sample_rate'])
        if existing is None:
            existing=connection.execute("""INSERT INTO sentinel_evaluation_online_samples
              (online_sample_id,organization_id,run_id,dataset_id,selected) VALUES (%s,%s,%s,%s,%s)
              RETURNING *""",(uuid4(),principal.organization_id,run_id,policy['dataset_id'],selected)).fetchone()
        if not selected: return {'selected':False,'reason':'rate_or_daily_limit','experiment_id':None}
        dataset_id=policy['dataset_id']; case_key=policy['case_key']; sample_id=existing['online_sample_id']
    report,_=create_experiment(database,principal,ExperimentCreate(
        idempotency_key='online-'+str(run_id),dataset_id=dataset_id,bindings={case_key:run_id}),
        semantic_judge,internal=True)
    with database.connect() as connection:
        connection.execute('UPDATE sentinel_evaluation_online_samples SET experiment_id=%s WHERE online_sample_id=%s',(report['experiment_id'],sample_id))
    return {'selected':True,'reason':'selected','experiment_id':report['experiment_id']}
