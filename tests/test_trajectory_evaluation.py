import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
from uuid import uuid4

from pydantic import ValidationError

from sentinel.evaluations import DatasetCreate, Expectations, dataset_definition, score_case
from sentinel.trajectory_evaluation import collect_facts

spec=importlib.util.spec_from_file_location('trajectory_gate',Path(__file__).resolve().parents[1]/'scripts'/'evaluation_gate.py')
gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


def row(*, status='succeeded', complete=True):
    model={'span_id':'model','parent_id':'root','name':'private.model.generate','kind':'model',
        'status':'completed','start_offset_ms':0,'duration_ms':60,
        'input_tokens':10 if complete else None,'output_tokens':5 if complete else None}
    return {'trace_id':uuid4(),'content_hash':'b'*64,'evidence':{'reported_status':status,'duration_ms':100,
        'spans':[model,
            {'span_id':'tool','parent_id':'root','name':'private.tool.respond','kind':'tool','status':'completed','start_offset_ms':70,'duration_ms':20,'input_tokens':None,'output_tokens':None},
            {'span_id':'root','parent_id':None,'name':'private.agent.run','kind':'agent','status':'completed','start_offset_ms':0,'duration_ms':100,'input_tokens':None,'output_tokens':None}]}}


_DEFAULT_ROW = object()


def collect(expected, value=_DEFAULT_ROW):
    connection=Mock()
    connection.execute.return_value.fetchone.return_value=row() if value is _DEFAULT_ROW else value
    return collect_facts(connection,uuid4(),uuid4(),expected)


class TrajectoryEvaluationTests(unittest.TestCase):
    def test_required_ordered_forbidden_and_summary_metrics(self):
        expected={'required_trace_spans':['private.agent.run','private.model.generate'],
            'ordered_trace_spans':['private.agent.run','private.model.generate','private.tool.respond'],
            'forbidden_trace_spans':['private.tool.delete'],'external_reported_status':'succeeded',
            'max_external_duration_ms':100,'max_reported_external_tokens':15,
            'reported_model_usage_complete':True,'max_external_spans':3,'max_failed_trace_spans':0}
        facts=collect(expected)
        self.assertTrue(all(facts[name] for name in expected))
        self.assertEqual((facts['reported_external_duration_ms'],facts['reported_external_span_count'],
            facts['reported_external_model_tokens']), (100,3,15))
        self.assertEqual(facts['external_trajectory_trust'],'caller_reported')

    def test_order_uses_timing_and_parent_depth_not_submission_order(self):
        good={'ordered_trace_spans':['private.agent.run','private.model.generate','private.tool.respond']}
        bad={'ordered_trace_spans':['private.tool.respond','private.model.generate']}
        self.assertTrue(collect(good)['ordered_trace_spans'])
        self.assertFalse(collect(bad)['ordered_trace_spans'])

    def test_missing_required_and_present_forbidden_spans_fail(self):
        expected={'required_trace_spans':['private.tool.delete'],
            'forbidden_trace_spans':['private.tool.respond']}
        facts=collect(expected)
        self.assertFalse(facts['required_trace_spans'])
        self.assertFalse(facts['forbidden_trace_spans'])

    def test_incomplete_reported_model_usage_fails_budget_but_can_be_expected(self):
        value=row(complete=False)
        expected={'max_reported_external_tokens':999,'reported_model_usage_complete':False}
        facts=collect(expected,value)
        self.assertFalse(facts['max_reported_external_tokens'])
        self.assertTrue(facts['reported_model_usage_complete'])
        self.assertEqual(facts['reported_external_model_tokens'],0)
        self.assertFalse(facts['reported_external_model_usage_complete'])

    def test_failed_and_needs_review_spans_share_failure_budget(self):
        value=row(); value['evidence']['spans'][0]['status']='needs_review'
        self.assertFalse(collect({'max_failed_trace_spans':0},value)['max_failed_trace_spans'])
        self.assertTrue(collect({'max_failed_trace_spans':1},value)['max_failed_trace_spans'])

    def test_missing_trace_fails_closed_without_inventing_zero_metrics(self):
        expected={'required_trace_spans':['private.agent.run'],'max_external_spans':10,
            'max_reported_external_tokens':100,'external_reported_status':'succeeded'}
        facts=collect(expected,None)
        self.assertTrue(all(facts[name] is False for name in expected))
        self.assertIsNone(facts['reported_external_span_count'])
        scored=score_case(expected,facts)
        self.assertFalse(scored['passed'])
        self.assertTrue(all(check['reason']=='missing_external_trace' for check in scored['checks']))

    def test_reports_hash_private_definitions_and_omit_span_names(self):
        expected={'required_trace_spans':['private.agent.run'],'forbidden_trace_spans':['private.tool.delete']}
        facts=collect(expected); scored=score_case(expected,facts)
        self.assertTrue(scored['passed'])
        self.assertNotIn('private.',str(facts)+str(scored))
        self.assertTrue(all(check['expected'] is True and len(check['definition_hash'])==64 for check in scored['checks']))

    def test_expectation_validation_rejects_duplicates_overlap_bad_names_and_coercion(self):
        invalid=[{'required_trace_spans':['same','same']},
            {'required_trace_spans':['same'],'forbidden_trace_spans':['same']},
            {'ordered_trace_spans':['same'],'forbidden_trace_spans':['same']},
            {'required_trace_spans':['UPPER']},{'required_trace_spans':[]},
            {'max_external_spans':0},{'max_external_duration_ms':True},
            {'reported_model_usage_complete':1}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValidationError): Expectations(**value)

    def test_serialization_preserves_rules_and_omits_new_null_defaults(self):
        body=DatasetCreate(slug='trajectory',version=1,cases=[{'case_key':'path','expected':{
            'required_trace_spans':['agent.run'],'max_external_duration_ms':0,'reported_model_usage_complete':False}}])
        expected=dataset_definition(body)['cases'][0]['expected']
        self.assertEqual(expected['required_trace_spans'],['agent.run'])
        self.assertEqual(expected['max_external_duration_ms'],0)
        self.assertIs(expected['reported_model_usage_complete'],False)
        self.assertNotIn('ordered_trace_spans',expected)

    def test_gate_accepts_v4_boolean_proofs_and_v4_mixed_output_checks(self):
        expected={'required_trace_spans':['private.agent.run']}; scored=score_case(expected,collect(expected))
        report={'evaluator_version':'agent_rules_v4','cases':[{'case_key':'path',**scored}],
            'total_cases':1,'passed_cases':1,'pass_rate':1.0,'gate':{'min_pass_rate':1.0,'passed':True}}
        self.assertTrue(gate.gate_passes(report))
        changed=copy.deepcopy(report); changed['evaluator_version']='agent_rules_v3'
        with self.assertRaises(ValueError): gate.gate_passes(changed)
        mixed=copy.deepcopy(report); mixed['cases'][0]['checks'][0]['rule']='output_schema'
        self.assertTrue(gate.gate_passes(mixed))


if __name__=='__main__': unittest.main()
