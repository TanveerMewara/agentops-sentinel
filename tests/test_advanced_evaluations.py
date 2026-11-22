import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from sentinel.advanced_evaluations import ExperimentAnalysisCreate, analyze_reports
from sentinel.evaluations import DatasetCreate, Expectations, score_case
from sentinel.semantic_judge import OpenAISemanticJudge

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_gate',ROOT/'scripts'/'release_gate.py')
release_gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(release_gate)


class AdvancedEvaluationTests(unittest.TestCase):
    def test_dataset_declares_heldout_category_coverage_and_strict_semantic_rule(self):
        body=DatasetCreate(slug='heldout',version=1,coverage={'min_categories':2,'min_cases_per_category':1},cases=[
            {'case_key':'billing','category':'billing','split':'test','expected':{'semantic_judge':{
                'criterion':'Answer must correctly resolve billing issue.','reference':{'answer':'ok'},
                'model_alias':'eval_judge'}}},
            {'case_key':'technical','category':'technical','split':'test','expected':{'run_status':'succeeded'}}])
        self.assertEqual(len(body.cases),2)
        with self.assertRaises(ValidationError):
            DatasetCreate(slug='bad',version=1,coverage={'min_categories':2},cases=[
                {'case_key':'only','category':'general','expected':{'run_status':'succeeded'}}])
        for invalid in ({'criterion':'short','reference':{},'model_alias':'eval_judge'},
                        {'criterion':'A valid criterion text','reference':{},'model_alias':'UPPER'}):
            with self.assertRaises(ValidationError): Expectations(semantic_judge=invalid)

    def test_openai_judge_uses_nonstored_strict_response_and_validates_consistency(self):
        response=Mock(output_text='{"score":0.8,"label":"pass","flags":[]}',id='resp')
        response.usage=Mock(input_tokens=10,output_tokens=4)
        create=Mock(return_value=response); factory=Mock(return_value=Mock(responses=Mock(create=create)))
        database=Mock(); cipher=Mock()
        with unittest.mock.patch('sentinel.semantic_judge.get_model_credential',return_value={
                'api_key':'secret','model_id':'judge-model'}):
            result=OpenAISemanticJudge(database,cipher,7,factory).evaluate(
                'org','eval_judge','A bounded evaluation criterion',{'answer':'reference'},{'answer':'candidate'})
        self.assertEqual((result.score,result.label,result.input_tokens,result.output_tokens),(0.8,'pass',10,4))
        kwargs=create.call_args.kwargs
        self.assertIs(kwargs['store'],False); self.assertTrue(kwargs['text']['format']['strict'])
        self.assertEqual(kwargs['max_output_tokens'],200); self.assertNotIn('secret',str(kwargs))

    def test_repeated_analysis_reports_uncertainty_categories_and_variants(self):
        def report(rate,passed,variant):
            return {'dataset_id':'dataset','evaluator_version':'agent_rules_v5','pass_rate':rate,
                'dataset_profile':{'held_out':True},'variant':variant,
                'cases':[{'category':'support','passed':passed}]}
        result=analyze_reports([report(1,True,{'prompt_version':'v1'}),report(0.5,False,{'prompt_version':'v2'})])
        self.assertEqual(result['mean_pass_rate'],0.75)
        self.assertEqual(result['pass_rate_stddev'],0.25)
        self.assertTrue(result['held_out']); self.assertEqual(result['categories']['support']['cases'],2)
        with self.assertRaises(ValidationError): ExperimentAnalysisCreate(experiment_ids=['00000000-0000-0000-0000-000000000001']*2)

    def test_semantic_score_and_release_gate_fail_closed_against_tampering(self):
        facts={'semantic_judge_passed':True,'semantic_judge_score':0.9,'semantic_judge_score_stddev':0.01,
            'semantic_judge_repetitions':3,'semantic_judge_config_hash':'a'*64,'semantic_judge_reason':'matched'}
        scored=score_case({'semantic_judge':{'private':'definition'}},facts)
        self.assertTrue(scored['passed']); self.assertNotIn('private',str(scored))
        report={'checks':{'mean_pass_rate':True,'pass_rate_stability':True,'held_out':True,
            'calibration':True,'regression':True},'candidate_analysis':{'experiment_count':2},'passed':True}
        self.assertTrue(release_gate.gate_passes(report))
        changed=copy.deepcopy(report); changed['passed']=False
        with self.assertRaises(ValueError): release_gate.gate_passes(changed)

    def test_release_gate_validator_recomputes_weighted_pass_rate(self):
        spec=importlib.util.spec_from_file_location('evaluation_gate',ROOT/'scripts'/'evaluation_gate.py')
        evaluation_gate=importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluation_gate)
        report={'evaluator_version':'agent_rules_v2','cases':[
            {'case_key':'important','weight':3.0,'passed':True,'checks':[{'rule':'run_status','expected':'succeeded','actual':'succeeded','passed':True}]},
            {'case_key':'minor','weight':1.0,'passed':False,'checks':[{'rule':'run_status','expected':'succeeded','actual':'failed','passed':False}]}],
            'passed_cases':1,'total_cases':2,'pass_rate':0.75,
            'gate':{'min_pass_rate':0.7,'passed':True}}
        self.assertTrue(evaluation_gate.gate_passes(report))


if __name__=='__main__': unittest.main()
