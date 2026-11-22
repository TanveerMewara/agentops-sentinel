"""Immutable, fact-based evaluations of saved runs. Never executes an agent."""
import hashlib
import json
import statistics
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from .security import require_roles
from .integrations.estateflow_evaluation import RULES as ESTATEFLOW_RULES
from .output_evaluation import RULES as OUTPUT_RULES, validate_definition
from .external_traces import canonical, read_trace_row
from .trajectory_evaluation import RULES as TRAJECTORY_RULES

SpanName = Annotated[str, StringConstraints(pattern=r'^[a-z][a-z0-9_.-]{0,79}$')]


class SemanticJudgeExpectation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    criterion: str = Field(min_length=10,max_length=2000)
    reference: JsonValue
    min_score: float = Field(default=0.7,ge=0,le=1,allow_inf_nan=False)
    model_alias: str = Field(pattern=r'^[a-z][a-z0-9_-]{2,63}$')
    repetitions: int = Field(default=3,ge=1,le=5,strict=True)


class CoverageRequirements(BaseModel):
    model_config = ConfigDict(extra='forbid')
    min_categories: int = Field(default=1,ge=1,le=50)
    min_cases_per_category: int = Field(default=1,ge=1,le=100)


class ExperimentVariant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt_version: str | None = Field(default=None,pattern=r'^[a-zA-Z0-9_.-]{1,80}$')
    model_alias: str | None = Field(default=None,pattern=r'^[a-z][a-z0-9_-]{2,63}$')
    retrieval_version: str | None = Field(default=None,pattern=r'^[a-zA-Z0-9_.-]{1,80}$')

    @model_validator(mode='after')
    def nonempty(self):
        if not self.model_dump(exclude_none=True): raise ValueError('Variant metadata cannot be empty.')
        return self


class Expectations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_status: str | None = Field(default=None, pattern=r"^(succeeded|failed|cancelled|needs_review)$")
    completed_bookings: int | None = Field(default=None, ge=0, le=100)
    property_bound: bool | None = None
    approvals_consumed: bool | None = None
    review_required: bool | None = None
    followup_status: str | None = Field(default=None, pattern=r"^(draft|approved|cancelled|blocked|not_created)$")
    max_steps_used: int | None = Field(default=None, ge=0, le=100)
    max_model_tokens: int | None = Field(default=None, ge=0, le=10000000)
    max_model_duration_ms: int | None = Field(default=None, ge=0, le=86400000)
    completed_tool_calls: int | None = Field(default=None, ge=0, le=100)
    failed_tool_calls: int | None = Field(default=None, ge=0, le=100)
    uncertain_tool_calls: int | None = Field(default=None, ge=0, le=100)
    max_tool_calls: int | None = Field(default=None, ge=0, le=100)
    required_approvals_consumed: bool | None = None
    output_equals: dict[str, JsonValue] | None = None
    output_schema: dict[str, JsonValue] | None = None
    required_trace_spans: list[SpanName] | None = Field(default=None, min_length=1, max_length=50)
    ordered_trace_spans: list[SpanName] | None = Field(default=None, min_length=1, max_length=50)
    forbidden_trace_spans: list[SpanName] | None = Field(default=None, min_length=1, max_length=50)
    external_reported_status: Literal['succeeded', 'failed', 'cancelled', 'needs_review'] | None = None
    max_external_duration_ms: int | None = Field(default=None, ge=0, le=86400000, strict=True)
    max_reported_external_tokens: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    reported_model_usage_complete: bool | None = Field(default=None, strict=True)
    max_external_spans: int | None = Field(default=None, ge=1, le=100, strict=True)
    max_failed_trace_spans: int | None = Field(default=None, ge=0, le=100, strict=True)
    semantic_judge: SemanticJudgeExpectation | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Each case needs at least one expectation.")
        if self.output_equals is not None:
            validate_definition(self.output_equals)
        if self.output_schema is not None:
            validate_definition(self.output_schema, schema=True)
        for names in (self.required_trace_spans, self.forbidden_trace_spans):
            if names is not None and len(set(names)) != len(names):
                raise ValueError('Required and forbidden span names must be unique.')
        required = set(self.required_trace_spans or ()) | set(self.ordered_trace_spans or ())
        if required & set(self.forbidden_trace_spans or ()):
            raise ValueError('A span cannot be both required and forbidden.')
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    category: str = Field(default='general',pattern=r'^[a-z][a-z0-9_-]{2,49}$')
    split: Literal['development','validation','test'] = 'test'
    weight: float = Field(default=1.0,gt=0,le=100,allow_inf_nan=False)
    expected: Expectations


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    version: int = Field(ge=1, le=1000000)
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)
    coverage: CoverageRequirements | None = None

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.case_key for case in self.cases}) != len(self.cases):
            raise ValueError("Case keys must be unique.")
        if self.coverage:
            counts={category:sum(case.category==category for case in self.cases)
                    for category in {case.category for case in self.cases}}
            if len(counts)<self.coverage.min_categories or min(counts.values())<self.coverage.min_cases_per_category:
                raise ValueError('Dataset does not meet its declared category coverage.')
        if len(canonical(self.model_dump(mode='json'))) > 262144:
            raise ValueError('Dataset exceeds the 256 KiB normalized limit.')
        return self


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=200)
    dataset_id: UUID
    bindings: dict[str, UUID] = Field(min_length=1, max_length=100)
    min_pass_rate: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)
    variant: ExperimentVariant | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def dataset_view(row):
    return {key: row[key] for key in ("dataset_id", "slug", "version", "definition", "created_at")}


def dataset_definition(body):
    definition = body.model_dump(mode="json")
    # Do not append new null defaults to the historical v1 definition/hash.
    # Existing nullable business rules retain their original serialization.
    for case in definition['cases']:
        if case.get('category')=='general': case.pop('category',None)
        if case.get('split')=='test': case.pop('split',None)
        if case.get('weight')==1.0: case.pop('weight',None)
        for name in ('completed_tool_calls','failed_tool_calls','uncertain_tool_calls','max_tool_calls','required_approvals_consumed','output_equals','output_schema',*TRAJECTORY_RULES):
            if case['expected'].get(name) is None:
                case['expected'].pop(name, None)
        if case['expected'].get('semantic_judge') is None:
            case['expected'].pop('semantic_judge',None)
    if definition.get('coverage') is None: definition.pop('coverage',None)
    return definition


def experiment_definition(body):
    value=body.model_dump(mode='json')
    if value.get('variant') is None: value.pop('variant',None)
    return value


def create_dataset(database, principal, body):
    require_roles("admin", "developer")(principal)
    definition = dataset_definition(body)
    payload_hash = digest(definition)
    with database.connect() as connection:
        row = connection.execute(
            """INSERT INTO sentinel_evaluation_datasets
               (dataset_id, organization_id, slug, version, definition, content_hash, created_by_key_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING *""",
            (uuid4(), principal.organization_id, body.slug, body.version, Jsonb(definition), payload_hash, principal.api_key_id),
        ).fetchone()
        created = row is not None
        if not created:
            row = connection.execute("SELECT * FROM sentinel_evaluation_datasets WHERE organization_id=%s AND slug=%s AND version=%s",
                                     (principal.organization_id, body.slug, body.version)).fetchone()
            if row["content_hash"] != payload_hash:
                raise HTTPException(409, "Dataset version already represents another definition.")
    return dataset_view(row), created


def list_datasets(database, principal, limit=50):
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM sentinel_evaluation_datasets WHERE organization_id=%s ORDER BY created_at DESC LIMIT %s",
                                  (principal.organization_id, limit)).fetchall()
    return [dataset_view(row) for row in rows]


def score_case(expected, facts):
    checks = []
    for name, value in expected.items():
        if value is None:
            continue
        if name == 'semantic_judge':
            actual=facts['semantic_judge_passed']
            checks.append({'rule':name,'expected':True,'actual':actual,'passed':actual,
                'definition_hash':digest(value),'score':facts['semantic_judge_score'],
                'score_stddev':facts['semantic_judge_score_stddev'],
                'repetitions':facts['semantic_judge_repetitions'],
                'judge_config_hash':facts['semantic_judge_config_hash'],
                'reason':'matched' if actual else facts['semantic_judge_reason']})
            continue
        if name in OUTPUT_RULES or name in TRAJECTORY_RULES:
            actual = facts[name]
            evidence_present = (facts.get('external_output_present') if name in OUTPUT_RULES
                                else facts.get('external_trajectory_present'))
            missing_reason = 'missing_external_output' if name in OUTPUT_RULES else 'missing_external_trace'
            checks.append({'rule': name, 'expected': True, 'actual': actual,
                'passed': actual is True, 'definition_hash': digest(value),
                'reason': (missing_reason if not evidence_present
                           else ('matched' if actual else 'mismatched'))})
            continue
        actual = facts[name.removeprefix("max_")] if name.startswith("max_") else facts[name]
        passed = actual <= value if name.startswith("max_") else actual == value
        checks.append({"rule": name, "expected": value, "actual": actual, "passed": passed})
    return {"passed": bool(checks) and all(check["passed"] for check in checks), "checks": checks}


def run_facts(connection, organization_id, run_id, expected, semantic_judge=None):
    run = connection.execute("SELECT status, steps_used, agent_version_id FROM sentinel_runs WHERE run_id=%s AND organization_id=%s",
                             (run_id, organization_id)).fetchone()
    if run is None:
        raise HTTPException(404, "Evaluation run not found.")
    if run["status"] in ("queued", "running"):
        raise HTTPException(409, "Offline evaluation requires a terminal run.")
    calls = connection.execute(
        """SELECT calls.status, calls.requires_approval,
                  EXISTS(SELECT 1 FROM sentinel_tool_call_approvals approvals
                    WHERE approvals.tool_call_id=calls.tool_call_id
                      AND approvals.organization_id=calls.organization_id
                      AND approvals.action_hash=calls.action_hash AND approvals.state='consumed') AS consumed
           FROM sentinel_tool_calls calls
           WHERE calls.run_id=%s AND calls.organization_id=%s""", (run_id, organization_id),
    ).fetchall()
    model = connection.execute(
        "SELECT coalesce(sum(total_tokens),0) AS tokens, coalesce(sum(duration_ms),0) AS duration FROM sentinel_model_invocations WHERE run_id=%s AND organization_id=%s",
        (run_id, organization_id),
    ).fetchone()
    facts = {"run_status": run["status"], "steps_used": run["steps_used"],
            "tool_calls": len(calls),
            "completed_tool_calls": sum(call['status'] == 'completed' for call in calls),
            "failed_tool_calls": sum(call['status'] == 'failed' for call in calls),
            "uncertain_tool_calls": sum(call['status'] in ('unknown', 'needs_review') for call in calls),
            "required_approvals_consumed": all(not call['requires_approval'] or call['consumed'] for call in calls if call['status'] == 'completed'),
            "model_tokens": int(model["tokens"]), "model_duration_ms": int(model["duration"]),
            "agent_version_id": str(run["agent_version_id"])}
    if {name for name, value in expected.items() if value is not None} & ESTATEFLOW_RULES:
        from .integrations.estateflow_evaluation import collect_facts
        facts.update(collect_facts(connection, organization_id, run_id))
    external_rules = {name for name, value in expected.items() if value is not None} & (OUTPUT_RULES | TRAJECTORY_RULES)
    trace_row = read_trace_row(connection, organization_id, run_id) if external_rules else None
    if external_rules & OUTPUT_RULES:
        from .output_evaluation import collect_facts
        facts.update(collect_facts(connection, organization_id, run_id, expected, row=trace_row))
    if external_rules & TRAJECTORY_RULES:
        from .trajectory_evaluation import collect_facts
        facts.update(collect_facts(connection, organization_id, run_id, expected, row=trace_row))
    semantic=expected.get('semantic_judge')
    if semantic is not None:
        trace_row=trace_row or read_trace_row(connection,organization_id,run_id)
        if trace_row is None or 'output' not in trace_row['evidence']:
            facts.update({'semantic_judge_passed':False,'semantic_judge_score':0.0,
                'semantic_judge_score_stddev':0.0,'semantic_judge_repetitions':0,
                'semantic_judge_config_hash':digest(semantic),'semantic_judge_reason':'missing_external_output'})
        else:
            if semantic_judge is None: raise HTTPException(409,'Semantic judge service is unavailable.')
            results=[semantic_judge.evaluate(organization_id,semantic['model_alias'],semantic['criterion'],
                semantic['reference'],trace_row['evidence']['output']) for _ in range(semantic['repetitions'])]
            scores=[item.score for item in results]; mean=sum(scores)/len(scores)
            facts.update({'semantic_judge_passed':mean>=semantic['min_score'],
                'semantic_judge_score':round(mean,6),
                'semantic_judge_score_stddev':round(statistics.pstdev(scores),6),
                'semantic_judge_repetitions':len(scores),
                'semantic_judge_config_hash':digest(semantic),
                'semantic_judge_reason':'below_threshold' if mean<semantic['min_score'] else 'matched',
                'semantic_judge_tokens':sum(x.input_tokens+x.output_tokens for x in results),
                'semantic_judge_duration_ms':sum(x.duration_ms for x in results),
                'semantic_judge_model_hash':digest(results[0].model_id)})
    return facts


def create_experiment(database, principal, body, semantic_judge=None, *, internal=False):
    if not internal: require_roles("admin", "developer", "reviewer")(principal)
    # Acquire the key lock before opening the repeatable-read snapshot, so a
    # concurrent replay sees the first experiment's committed frozen report.
    with database.connect() as lock_connection:
        lock_connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                (f"evaluation:{principal.organization_id}:{body.idempotency_key}",))
        return _create_experiment_snapshot(database, principal, body, semantic_judge, internal=internal)


def _create_experiment_snapshot(database, principal, body, semantic_judge=None, *, internal=False):
    if not internal: require_roles("admin", "developer", "reviewer")(principal)
    payload_hash = digest(experiment_definition(body))
    with database.connect() as connection:
        # One consistent snapshot includes all cases and their business-state facts.
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        previous = connection.execute("SELECT * FROM sentinel_evaluation_experiments WHERE organization_id=%s AND idempotency_key=%s",
                                      (principal.organization_id, body.idempotency_key)).fetchone()
        if previous:
            if previous["request_hash"] != payload_hash:
                raise HTTPException(409, "Experiment key already represents another request.")
            return previous["report"], False
        dataset = connection.execute("SELECT * FROM sentinel_evaluation_datasets WHERE dataset_id=%s AND organization_id=%s",
                                     (body.dataset_id, principal.organization_id)).fetchone()
        if dataset is None:
            raise HTTPException(404, "Evaluation dataset not found.")
        cases = dataset["definition"]["cases"]
        if (any(case['expected'].get('semantic_judge') is not None for case in cases)
                and not internal and principal.role not in ('admin','developer')):
            raise HTTPException(403,'Only admin or developer keys can start provider-backed semantic evaluation.')
        if set(body.bindings) != {case["case_key"] for case in cases}:
            raise HTTPException(422, "Bind every dataset case exactly once; extra cases are not allowed.")
        results = []
        for case in cases:
            run_id = body.bindings[case["case_key"]]
            facts = run_facts(connection, principal.organization_id, run_id, case['expected'], semantic_judge)
            results.append({"case_key": case["case_key"], "run_id": str(run_id),
                            'category':case.get('category','general'),'split':case.get('split','test'),
                            'weight':case.get('weight',1.0),
                            "facts": facts, **score_case(case["expected"], facts)})
        passed = sum(result["passed"] for result in results)
        total_weight=sum(float(result['weight']) for result in results)
        rate = sum(float(result['weight']) for result in results if result['passed']) / total_weight
        report = {"experiment_id": str(uuid4()), "dataset_id": str(body.dataset_id),
                  "dataset_slug": dataset["slug"], "dataset_version": dataset["version"],
                  "evaluator_version": ('agent_rules_v5' if any(
                      case['expected'].get('semantic_judge') is not None for case in cases
                  ) else 'agent_rules_v4' if any(
                      case['expected'].get(name) is not None for case in cases for name in TRAJECTORY_RULES
                  ) else 'agent_rules_v3' if any(
                      case['expected'].get(name) is not None for case in cases for name in OUTPUT_RULES
                  ) else 'agent_rules_v2'), "cases": results,
                  "passed_cases": passed, "total_cases": len(results), "pass_rate": rate,
                  'variant':body.variant.model_dump(exclude_none=True) if body.variant else None,
                  'dataset_profile':{'case_count':len(cases),
                    'held_out':all(case.get('split','test')=='test' for case in cases),
                    'categories':{category:sum(case.get('category','general')==category for case in cases)
                                  for category in sorted({case.get('category','general') for case in cases})},
                    'total_weight':total_weight},
                  "gate": {"min_pass_rate": body.min_pass_rate, "passed": rate >= body.min_pass_rate}}
        connection.execute(
            """INSERT INTO sentinel_evaluation_experiments
               (experiment_id, organization_id, dataset_id, idempotency_key, request_hash, report, created_by_key_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (report["experiment_id"], principal.organization_id, body.dataset_id, body.idempotency_key,
             payload_hash, Jsonb(report), principal.api_key_id),
        )
    return report, True


def list_experiments(database, principal, limit=50):
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        return [row["report"] for row in connection.execute(
            "SELECT report FROM sentinel_evaluation_experiments WHERE organization_id=%s ORDER BY created_at DESC LIMIT %s",
            (principal.organization_id, limit)).fetchall()]


def compare_experiments(database, principal, left, right):
    require_roles("admin", "developer", "reviewer")(principal)
    with database.connect() as connection:
        reports = {str(row["experiment_id"]): row["report"] for row in connection.execute(
            "SELECT experiment_id, report FROM sentinel_evaluation_experiments WHERE organization_id=%s AND experiment_id IN (%s,%s)",
            (principal.organization_id, left, right)).fetchall()}
    if str(left) not in reports or str(right) not in reports:
        raise HTTPException(404, "Evaluation experiment not found.")
    before, after = reports[str(left)], reports[str(right)]
    if before["dataset_id"] != after["dataset_id"]:
        raise HTTPException(409, "Compare experiments from the same dataset version.")
    if before['evaluator_version'] != after['evaluator_version']:
        raise HTTPException(409, 'Compare experiments using the same evaluator version.')
    def category_rates(report):
        categories={case.get('category','general') for case in report['cases']}
        return {category:sum(case['passed'] for case in report['cases'] if case.get('category','general')==category)/
                sum(case.get('category','general')==category for case in report['cases']) for category in categories}
    before_categories=category_rates(before); after_categories=category_rates(after)
    semantic_before=[check['score'] for case in before['cases'] for check in case['checks'] if check['rule']=='semantic_judge']
    semantic_after=[check['score'] for case in after['cases'] for check in case['checks'] if check['rule']=='semantic_judge']
    return {"left": before, "right": after, "pass_rate_delta": after["pass_rate"] - before["pass_rate"],
            'variant_change':{'left':before.get('variant'),'right':after.get('variant')},
            'category_pass_rate_delta':{category:after_categories.get(category,0)-before_categories.get(category,0)
                for category in sorted(set(before_categories)|set(after_categories))},
            'semantic_score_delta':((sum(semantic_after)/len(semantic_after))-(sum(semantic_before)/len(semantic_before))
                                    if semantic_before and semantic_after else None)}
