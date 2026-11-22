"""Repeatable local fault checks; report identifiers and status, never tracebacks."""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
REPORT = ROOT / ".local" / "failure-lab" / "latest.json"
MODULES = ("test_booking_failure_lab", "test_booking_recovery", "test_provider_circuit", "test_adapters",
           "test_worker_runtime", "test_client_network", "test_worker_network")


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in MODULES)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    report = {
        "run_id": uuid4().hex,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "passing" if result.wasSuccessful() else "failing",
        "tests_run": result.testsRun,
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [test.id() for test, _ in result.skipped],
        "modules": list(MODULES),
        "production_ready": False,
        "boundary": "Local fictional providers; no real provider or multi-host reliability claim.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_name(report["run_id"] + ".tmp")
    try:
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Failure lab: {report['status']} ({result.testsRun} checks).")
    print("Report: .local/failure-lab/latest.json")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
