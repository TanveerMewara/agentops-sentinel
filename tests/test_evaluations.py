import copy
import importlib.util
from pathlib import Path
import unittest

from pydantic import ValidationError
from sentinel.evaluations import DatasetCreate, Expectations, score_case

spec = importlib.util.spec_from_file_location("evaluation_gate", Path(__file__).resolve().parents[1] / "scripts" / "evaluation_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class EvaluationTests(unittest.TestCase):
    def test_empty_unknown_and_duplicate_rules_are_rejected(self):
        for value in ({}, {"customer_name": "Private"}, {"max_model_tokens": -1}):
            with self.assertRaises(ValidationError):
                Expectations(**value)
        with self.assertRaises(ValidationError):
            DatasetCreate(slug="sample", version=1, cases=[
                {"case_key": "same", "expected": {"run_status": "succeeded"}}] * 2)

    def test_zero_budgets_and_false_expectations_are_scored(self):
        result = score_case({"max_model_tokens": 0, "property_bound": False},
                            {"model_tokens": 1, "property_bound": False})
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"][0]["passed"])
        self.assertTrue(result["checks"][1]["passed"])

    def report(self):
        result = score_case({"run_status": "succeeded"}, {"run_status": "failed"})
        return {"evaluator_version": "business_rules_v1", "cases": [{"case_key": "outcome", **result}],
                "passed_cases": 0, "total_cases": 1, "pass_rate": 0.0,
                "gate": {"min_pass_rate": 1.0, "passed": False}}

    def test_gate_rejects_fabricated_summary_and_pass_flags(self):
        report = self.report()
        self.assertFalse(gate.gate_passes(report))
        fake = copy.deepcopy(report)
        fake["gate"]["passed"] = True
        with self.assertRaises(ValueError):
            gate.gate_passes(fake)
        fake = copy.deepcopy(report)
        fake["cases"][0]["checks"][0]["passed"] = True
        with self.assertRaises(ValueError):
            gate.gate_passes(fake)
        fake = copy.deepcopy(report)
        fake["pass_rate"] = 1.0
        with self.assertRaises(ValueError):
            gate.gate_passes(fake)

    def test_gate_requires_cases_and_valid_threshold(self):
        for mutation in ({"cases": []}, {"gate": {"min_pass_rate": float('nan'), "passed": False}}):
            with self.assertRaises(ValueError):
                gate.gate_passes({**self.report(), **mutation})

    def test_gate_accepts_new_general_version_and_retains_legacy_exports(self):
        report=self.report()
        self.assertFalse(gate.gate_passes(report))
        self.assertFalse(gate.gate_passes({**report,'evaluator_version':'agent_rules_v2'}))
        with self.assertRaises(ValueError): gate.gate_passes({**report,'evaluator_version':'invented_version'})
