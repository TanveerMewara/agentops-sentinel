import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location("security_lab", Path(__file__).resolve().parents[1] / "scripts" / "security_lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class SecurityLabReportTests(unittest.TestCase):
    def report(self, case):
        loader = Mock()
        loader.loadTestsFromName.return_value = unittest.TestSuite([case])
        return lab.run_checks({"fixture": ("controlled_fixture",)}, loader)

    def test_failing_subtests_cannot_leak_payloads_or_tracebacks(self):
        marker = "PRIVATE_REPORT_CANARY"

        class Fixture(unittest.TestCase):
            def runTest(self):
                print(marker)
                with self.subTest(secret=marker):
                    self.fail(marker)

        report = self.report(Fixture())
        self.assertEqual(report["status"], "failing")
        self.assertNotIn(marker, json.dumps(report))
        self.assertFalse(report["production_ready"])
        self.assertIsNone(report["security_score"])

    def test_skips_and_empty_suites_cannot_claim_passing(self):
        class Fixture(unittest.TestCase):
            def runTest(self):
                self.skipTest("PRIVATE_SKIP_CANARY")

        report = self.report(Fixture())
        self.assertEqual(report["status"], "partial")
        self.assertNotIn("PRIVATE_SKIP_CANARY", json.dumps(report))
        self.assertEqual(lab.run_checks({})["status"], "partial")

    def test_expected_failures_cannot_claim_complete_passing(self):
        class Fixture(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                self.fail("PRIVATE_EXPECTED_FAILURE_CANARY")

        report = self.report(Fixture())
        self.assertEqual(report["status"], "partial")
        self.assertNotIn("PRIVATE_EXPECTED_FAILURE_CANARY", json.dumps(report))

    def test_atomic_report_replaces_previous_failure_without_temp_files(self):
        class Fixture(unittest.TestCase):
            def runTest(self):
                pass

        report = self.report(Fixture())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "latest.json"
            target.write_text('{"status":"failing"}')
            lab.save_report(report, target)
            self.assertEqual(json.loads(target.read_text())["status"], "passing")
            self.assertEqual(list(Path(directory).iterdir()), [target])
