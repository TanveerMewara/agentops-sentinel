import unittest

from sentinel.failure_diagnostics import FailureObservation, diagnose


class FailureDiagnosticsTests(unittest.TestCase):
    def test_every_primary_signal_maps_to_its_declared_category(self):
        cases = {
            "tool_execution_failure": {"tool_status": "failed"},
            "timeout": {"timed_out": True},
            "invalid_tool_arguments": {"tool_arguments_valid": False},
            "malformed_llm_output": {"llm_output_valid": False},
            "hallucinated_unsupported_response": {"response_supported": False},
            "api_failure": {"api_status": 503},
            "retry_exhaustion": {"retry_exhausted": True},
            "routing_failure": {"route_valid": False},
            "retrieval_failure": {"retrieval_sufficient": False},
            "validation_failure": {"validation_passed": False},
        }
        for expected, signals in cases.items():
            with self.subTest(expected):
                self.assertEqual(diagnose(FailureObservation.from_mapping(signals)).category, expected)
        self.assertEqual(diagnose(FailureObservation()).category, "no_failure")

    def test_precedence_is_stable_for_overlapping_normalized_signals(self):
        observation = FailureObservation.from_mapping({
            "timed_out": True, "tool_status": "failed", "retry_exhausted": True})
        self.assertEqual(diagnose(observation).category, "timeout")

    def test_observations_reject_unknown_coerced_and_invalid_values(self):
        for value in ({"private_error": "secret"}, {"timed_out": 1},
                      {"api_status": True}, {"api_status": 700}, {"tool_status": "unknown"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FailureObservation.from_mapping(value)
