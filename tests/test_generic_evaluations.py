import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sentinel.evaluations import DatasetCreate, Expectations, dataset_definition, run_facts, score_case, compare_experiments
from sentinel.workflow import require_estateflow_workflow
from sentinel.client import SentinelClient


class Connection:
    def __init__(self, *, status='succeeded', calls=()):
        self.status, self.calls, self.queries = status, calls, []
    def execute(self, sql, params):
        self.queries.append((sql, params))
        if 'estate_' in sql:
            raise AssertionError('Generic evaluation must not read example tables.')
        if 'FROM sentinel_runs' in sql:
            return Mock(fetchone=lambda: None if self.status is None else {'status': self.status, 'steps_used': 2, 'agent_version_id': uuid4()})
        if 'FROM sentinel_tool_calls' in sql:
            return Mock(fetchall=lambda: self.calls)
        if 'FROM sentinel_model_invocations' in sql:
            return Mock(fetchone=lambda: {'tokens': 17, 'duration': 80})
        raise AssertionError('Unexpected query.')


class GenericEvaluationTests(unittest.TestCase):
    def test_legacy_dataset_definition_keeps_its_exact_serialized_shape(self):
        body=DatasetCreate(slug='legacy',version=1,cases=[{'case_key':'outcome','expected':{'run_status':'succeeded'}}])
        self.assertEqual(dataset_definition(body), {'slug':'legacy','version':1,'cases':[{'case_key':'outcome','expected':{
            'run_status':'succeeded','completed_bookings':None,'property_bound':None,'approvals_consumed':None,
            'review_required':None,'followup_status':None,'max_steps_used':None,'max_model_tokens':None,'max_model_duration_ms':None}}]})

    def test_new_zero_and_false_rules_survive_dataset_serialization(self):
        body=DatasetCreate(slug='generic',version=1,cases=[{'case_key':'outcome','expected':{'max_tool_calls':0,'required_approvals_consumed':False}}])
        expected=dataset_definition(body)['cases'][0]['expected']
        self.assertEqual(expected['max_tool_calls'],0)
        self.assertIs(expected['required_approvals_consumed'],False)
        self.assertNotIn('completed_tool_calls',expected)

    def test_generic_cases_do_not_query_business_tables_even_with_null_legacy_rules(self):
        c = Connection()
        org, run = uuid4(), uuid4()
        facts = run_facts(c, org, run, Expectations(run_status='succeeded').model_dump())
        self.assertEqual(facts['tool_calls'], 0)
        self.assertNotIn('completed_bookings', facts)
        self.assertTrue(facts['required_approvals_consumed'])
        self.assertTrue(score_case({'run_status':'succeeded','max_model_tokens':17,'max_tool_calls':0}, facts)['passed'])
        for sql, params in c.queries:
            self.assertEqual(params, (run, org))
            self.assertNotIn('calls.arguments', sql)
            self.assertNotIn('calls.result', sql)

    def test_tools_of_any_domain_have_distinct_completion_failure_and_uncertainty(self):
        statuses = ['completed','completed','failed','unknown','needs_review','cancelled','reserved']
        c = Connection(calls=[{'status':status,'requires_approval':False,'consumed':False} for status in statuses])
        facts = run_facts(c, uuid4(), uuid4(), {'completed_tool_calls':2})
        self.assertEqual([facts[name] for name in ['tool_calls','completed_tool_calls','failed_tool_calls','uncertain_tool_calls']], [7,2,1,2])
        self.assertFalse(score_case({'max_tool_calls':6}, facts)['passed'])

    def test_required_approvals_cannot_be_inferred_from_run_success(self):
        c = Connection(calls=[{'status':'completed','requires_approval':True,'consumed':False}])
        facts = run_facts(c, uuid4(), uuid4(), {'required_approvals_consumed':True})
        self.assertFalse(score_case({'required_approvals_consumed':True}, facts)['passed'])
        sql = c.queries[1][0]
        self.assertIn('approvals.action_hash=calls.action_hash', sql)
        self.assertIn('approvals.organization_id=calls.organization_id', sql)
        c.calls[0]['consumed'] = True
        self.assertTrue(run_facts(c,uuid4(),uuid4(),{})['required_approvals_consumed'])

    def test_false_example_expectation_explicitly_activates_example_collector(self):
        with patch('sentinel.integrations.estateflow_evaluation.collect_facts', return_value={'property_bound':False}) as collector:
            c=Connection()
            org,run=uuid4(),uuid4()
            facts=run_facts(c,org,run,{'property_bound':False})
            collector.assert_called_once_with(c,org,run)
            self.assertFalse(facts['property_bound'])

    def test_missing_and_nonterminal_runs_stop_before_metric_queries(self):
        for status,code in [(None,404),('queued',409),('running',409)]:
            c=Connection(status=status)
            with self.assertRaises(HTTPException) as error:
                run_facts(c,uuid4(),uuid4(),{'completed_tool_calls':0})
            self.assertEqual(error.exception.status_code,code)
            self.assertEqual(len(c.queries),1)

    def test_general_expectations_enforce_limits(self):
        self.assertEqual(Expectations(completed_tool_calls=0,failed_tool_calls=0,uncertain_tool_calls=0,max_tool_calls=0,required_approvals_consumed=False).max_tool_calls,0)
        for name in ['completed_tool_calls','failed_tool_calls','uncertain_tool_calls','max_tool_calls']:
            for value in [-1,101]:
                with self.assertRaises(ValidationError): Expectations(**{name:value})

    def test_comparison_rejects_different_evaluator_versions(self):
        left,right,dataset=uuid4(),uuid4(),str(uuid4())
        rows=[{'experiment_id':left,'report':{'dataset_id':dataset,'evaluator_version':'business_rules_v1'}},
              {'experiment_id':right,'report':{'dataset_id':dataset,'evaluator_version':'agent_rules_v2'}}]
        class Database:
            @contextmanager
            def connect(self): yield Mock(execute=lambda *args: Mock(fetchall=lambda: rows))
        with self.assertRaises(HTTPException) as error:
            compare_experiments(Database(),Mock(role='developer',organization_id=uuid4()),left,right)
        self.assertEqual(error.exception.status_code,409)

    def test_external_runs_cannot_accidentally_enter_example_graph(self):
        for payload,alias in [({},'external_agent'),({'workflow':'external_support_triage'},'deterministic_estateflow'),({'workflow':False},'external_agent')]:
            with self.assertRaises(HTTPException) as error: require_estateflow_workflow(payload,alias)
            self.assertEqual(error.exception.status_code,409)
        require_estateflow_workflow({'workflow':'estateflow'},'deterministic_estateflow')
        require_estateflow_workflow({},'deterministic_estateflow')

    def test_new_client_versions_default_to_external_metadata(self):
        client=SentinelClient('http://127.0.0.1:8020','snt_fixture_key')
        client.request=Mock()
        client.create_version('agent','1.0.0','External runtime')
        self.assertEqual(client.request.call_args.args[1]['model_alias'],'external_agent')
