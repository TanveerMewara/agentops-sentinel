import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
from uuid import uuid4

from pydantic import ValidationError
from sentinel.evaluations import Expectations, DatasetCreate, dataset_definition, score_case
from sentinel.output_evaluation import collect_facts

spec=importlib.util.spec_from_file_location('output_gate',Path(__file__).resolve().parents[1]/'scripts'/'evaluation_gate.py')
gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


def facts(expected, output=None, *, present=True):
    row={'trace_id':uuid4(),'content_hash':'a'*64,'evidence':{'output':output}} if present else None
    connection=Mock(execute=lambda *args:Mock(fetchone=lambda:row))
    return collect_facts(connection,uuid4(),uuid4(),expected)


class OutputEvaluationTests(unittest.TestCase):
    def test_exact_output_ignores_key_order_but_preserves_values_and_array_order(self):
        expected={'output_equals':{'a':1,'b':['first','second']}}
        self.assertTrue(facts(expected,{'b':['first','second'],'a':1})['output_equals'])
        self.assertTrue(facts(expected,{'b':['first','second'],'a':1.0})['output_equals'])
        for output in ({'a':True,'b':['first','second']},{'a':1,'b':['second','first']},
                       {'a':1,'b':['first','second'],'extra':0}):
            self.assertFalse(facts(expected,output)['output_equals'])

    def test_schema_checks_nested_types_required_enum_and_extra_fields(self):
        schema={'type':'object','required':['answer','items'],'additionalProperties':False,
            'properties':{'answer':{'type':'string','minLength':2},'items':{'type':'array','minItems':1,
                'items':{'type':'object','required':['priority'],'properties':{'priority':{'enum':['low','high']}},'additionalProperties':False}}}}
        Expectations(output_schema=schema)
        expected={'output_schema':schema}
        self.assertTrue(facts(expected,{'answer':'ok','items':[{'priority':'low'}]})['output_schema'])
        for output in ({'answer':'ok'},{'answer':True,'items':[{'priority':'low'}]},
                       {'answer':'ok','items':[{'priority':'invalid'}]},
                       {'answer':'ok','items':[{'priority':'low'}],'unexpected':True}):
            self.assertFalse(facts(expected,output)['output_schema'])

    def test_unsupported_schema_features_and_invalid_definitions_rejected(self):
        for schema in ({'$ref':'https://example.invalid/private'}, {'pattern':'(a+)+$'},
            {'format':'email'}, {'oneOf':[{},{}]}, {'type':'not-a-type'},
            {'properties':{'answer':{'$ref':'#/$defs/answer'}}}, {'$schema':'https://example.invalid/schema'},
            {'required':'answer'}, {'items':42}):
            with self.subTest(schema=schema),self.assertRaises(ValidationError): Expectations(output_schema=schema)

    def test_output_rules_have_finite_size_and_schema_depth_limits(self):
        for output in ({'value':float('nan')},{'value':float('inf')},{'value':'界'*6000}):
            with self.assertRaises(ValidationError): Expectations(output_equals=output)
        schema={'type':'string'}
        for _ in range(18): schema={'properties':{'nested':schema}}
        with self.assertRaises(ValidationError): Expectations(output_schema=schema)
        with self.assertRaises(ValidationError): Expectations(output_schema={'properties':{str(i):{} for i in range(257)}})

    def test_missing_evidence_fails_even_an_empty_schema_or_reference(self):
        expected={'output_equals':{},'output_schema':{}}
        scored=score_case(expected,facts(expected,present=False))
        self.assertFalse(scored['passed'])
        self.assertTrue(all(check['reason']=='missing_external_output' for check in scored['checks']))

    def test_total_dataset_size_is_bounded_across_individually_valid_rules(self):
        with self.assertRaises(ValidationError):
            DatasetCreate(slug='large',version=1,cases=[{'case_key':f'case-{index}',
                'expected':{'output_equals':{'value':'x'*9000}}} for index in range(32)])

    def test_reports_omit_outputs_references_and_schema_property_names(self):
        expected={'output_equals':{'PRIVATE-KEY':'PRIVATE-ANSWER'},
            'output_schema':{'properties':{'PRIVATE-KEY':{'const':'PRIVATE-ANSWER'}}}}
        collected=facts(expected,{'PRIVATE-KEY':'PRIVATE-ANSWER'})
        scored=score_case(expected,collected)
        self.assertTrue(scored['passed'])
        self.assertNotIn('PRIVATE',str(collected)+str(scored))
        self.assertEqual(collected['external_output_trust'],'caller_reported')
        self.assertTrue(all(check['expected'] is True for check in scored['checks']))

    def test_tenant_scope_and_empty_reference_survives_serialization(self):
        org,run=uuid4(),uuid4(); connection=Mock()
        connection.execute.return_value.fetchone.return_value=None
        collect_facts(connection,org,run,{'output_equals':{}})
        self.assertEqual(connection.execute.call_args.args[1],(run,org))
        body=DatasetCreate(slug='output',version=1,cases=[{'case_key':'answer','expected':{'output_equals':{}}}])
        expected=dataset_definition(body)['cases'][0]['expected']
        self.assertEqual(expected['output_equals'],{})
        self.assertNotIn('output_schema',expected)

    def test_export_gate_supports_v3_checks_and_rejects_invalid_boolean_proofs(self):
        expected={'output_equals':{'answer':'ok'}}; scored=score_case(expected,facts(expected,{'answer':'ok'}))
        report={'evaluator_version':'agent_rules_v3','cases':[{'case_key':'answer',**scored}],
            'total_cases':1,'passed_cases':1,'pass_rate':1.0,'gate':{'min_pass_rate':1.0,'passed':True}}
        self.assertTrue(gate.gate_passes(report))
        for mutation in ({'actual':1},{'expected':False},{'definition_hash':'invalid'}):
            changed=copy.deepcopy(report); changed['cases'][0]['checks'][0].update(mutation)
            with self.assertRaises(ValueError): gate.gate_passes(changed)
        with self.assertRaises(ValueError): gate.gate_passes({**report,'evaluator_version':'agent_rules_v2'})
