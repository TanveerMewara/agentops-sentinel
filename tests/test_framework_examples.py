import unittest

from examples.langgraph_external_agent import execute as execute_langgraph
from examples.openai_agents_sdk_agent import (
    execute as execute_openai_agents, sanitized_classification,
)


class FrameworkExampleTests(unittest.TestCase):
    def test_langgraph_success_failure_and_interrupt(self):
        expected = {
            "success": ("succeeded", {"value": 2}),
            "failed": ("failed", {"error_code": "execution_failed"}),
            "interrupted": ("needs_review", {"status": "interrupted"}),
        }
        for mode, (status, output) in expected.items():
            with self.subTest(mode=mode):
                evidence, result = execute_langgraph(mode)
                self.assertEqual((evidence["reported_status"], result), (status, output))
                self.assertTrue(evidence["spans"])
                self.assertNotIn("Deliberate example failure", str(evidence))

    def test_openai_agents_offline_failure_and_interrupt(self):
        expected = {
            "offline": ("succeeded", {"category": "technical", "priority": "standard"}),
            "failed": ("failed", {"error_code": "execution_failed"}),
            "interrupted": ("needs_review", {"status": "interrupted"}),
        }
        for mode, (status, output) in expected.items():
            with self.subTest(mode=mode):
                evidence, result = execute_openai_agents(mode)
                self.assertEqual((evidence["reported_status"], result), (status, output))
                self.assertTrue(evidence["spans"])
                self.assertNotIn("offline-fixture", str(evidence))

    def test_openai_agents_live_mode_requires_explicit_credentials_and_model(self):
        import os
        previous = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                execute_openai_agents("live", model="explicit-model")
        finally:
            if previous is not None:
                os.environ["OPENAI_API_KEY"] = previous

    def test_live_output_is_reduced_to_bounded_classification(self):
        self.assertEqual(sanitized_classification(" Billing:Urgent "),
                         {"category": "billing", "priority": "urgent"})
        with self.assertRaisesRegex(ValueError, "unsupported classification"):
            sanitized_classification("PRIVATE free-form model response")


if __name__ == "__main__":
    unittest.main()
