"""A stopped or partially passing release check must never report success."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("release_check", Path(__file__).resolve().parents[1] / "scripts" / "release_check.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


class ReleaseCheckTests(unittest.TestCase):
    def test_failure_stops_later_checks_and_persists_failure(self):
        codes, saved = iter((0, 1)), []
        stages = [(name, [name], release_check.ROOT) for name in ("first", "second", "third")]
        report = {"status": "running", "production_ready": False}
        def run(*args, **kwargs):
            return SimpleNamespace(returncode=next(codes))
        def persist(value):
            saved.append(value["status"])
        self.assertFalse(release_check.execute(stages, report, run=run, persist=persist))
        self.assertEqual([stage["status"] for stage in report["stages"]], ["passed", "failed", "not_run"])
        self.assertEqual(saved[-1], "failed")
        self.assertFalse(report["production_ready"])

    def test_interrupt_is_recorded_without_error_payload(self):
        report = {"status": "running", "production_ready": False}
        def run(*args, **kwargs):
            raise KeyboardInterrupt("PRIVATE-SYNTHETIC-CONTENT")
        self.assertFalse(release_check.execute([("first", ["first"], release_check.ROOT)], report,
                                              run=run, persist=lambda _: None))
        self.assertEqual(report["status"], "interrupted")
        self.assertNotIn("PRIVATE-SYNTHETIC-CONTENT", str(report))

    def test_passing_profile_remains_local_evidence(self):
        report = {"status": "running", "production_ready": False}
        self.assertTrue(release_check.execute([("first", ["first"], release_check.ROOT)], report,
            run=lambda *a, **k: SimpleNamespace(returncode=0), persist=lambda _: None))
        self.assertEqual(report["status"], "passed")
        self.assertFalse(report["production_ready"])
