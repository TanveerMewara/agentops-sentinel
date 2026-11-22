from decimal import Decimal
from pathlib import Path
import unittest

from benchmarks.workloads import cost_summary, execute_scenario, load_scenarios


ROOT = Path(__file__).resolve().parents[1]


class BenchmarkWorkloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios, cls.dataset_hash = load_scenarios(ROOT / "datasets" / "failure-detection-v1.json")

    def test_dataset_is_hashed_unique_and_covers_success_and_failures(self):
        self.assertEqual(len(self.dataset_hash), 64)
        self.assertEqual(len({item.scenario_id for item in self.scenarios}), len(self.scenarios))
        self.assertIn("no_failure", {item.ground_truth for item in self.scenarios})
        self.assertGreater(len({item.ground_truth for item in self.scenarios}), 10)

    def test_observed_and_optimized_preserve_diagnosis_while_optimization_reduces_usage(self):
        scenario = next(item for item in self.scenarios if item.ground_truth != "no_failure")
        observed = execute_scenario(scenario, "observed", model_delay_seconds=.00001,
                                    tool_delay_seconds=.00001)
        optimized = execute_scenario(scenario, "optimized", model_delay_seconds=.00001,
                                     tool_delay_seconds=.00001)
        self.assertEqual(observed["prediction"], scenario.ground_truth)
        self.assertEqual(optimized["prediction"], scenario.ground_truth)
        self.assertLess(optimized["input_tokens"], observed["input_tokens"])
        self.assertEqual((observed["model_calls"], optimized["model_calls"]), (2, 1))
        costs = cost_summary([observed], Decimal(".5"), Decimal("1.5"))
        self.assertEqual(costs["evidence"], "deterministic_synthetic_provider_usage")
