"""Run discoverable unit tests under branch coverage and save structured evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


def main() -> int:
    try:
        import coverage
    except ImportError:
        print("coverage.py is required; install requirements-dev.txt", file=sys.stderr)
        return 2
    reports = ROOT / "reports"; reports.mkdir(exist_ok=True)
    coverage_file = reports / ".coverage"
    cov = coverage.Coverage(source=[str(ROOT / "src" / "sentinel")], branch=True,
                            data_file=str(coverage_file), omit=["*/migrations/*"])
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    stream = io.StringIO()
    cov.start()
    try:
        result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    finally:
        cov.stop(); cov.save()
    coverage_json = reports / "coverage.json"
    cov.json_report(outfile=str(coverage_json), pretty_print=True)
    details = json.loads(coverage_json.read_text(encoding="utf-8"))
    important = {}
    requested = ("failure_diagnostics.py", "evaluations.py", "telemetry.py", "trace_recorder.py",
                 "model_gateway.py", "runs.py", "external_traces.py")
    for filename, values in details["files"].items():
        if Path(filename).name in requested:
            important[Path(filename).name] = round(values["summary"]["percent_covered"], 2)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors) - len(result.skipped)
    report = {
        "completed_at": datetime.now(timezone.utc).isoformat(), "total": total,
        "passed": passed, "failed": len(result.failures), "errors": len(result.errors),
        "skipped": len(result.skipped), "pass_rate": round(passed / total, 6) if total else 0,
        "successful": result.wasSuccessful(),
        "failure_ids": [test.id() for test, _ in result.failures],
        "error_ids": [test.id() for test, _ in result.errors],
        "skipped_ids": [test.id() for test, _ in result.skipped],
        "coverage": {"percent": round(details["totals"]["percent_covered"], 2),
                     "covered_lines": details["totals"]["covered_lines"],
                     "missing_lines": details["totals"]["missing_lines"],
                     "num_statements": details["totals"]["num_statements"],
                     "important_modules_percent": important,
                     "scope": "discoverable test_*.py unit suite; src/sentinel; branch coverage enabled"},
    }
    target = reports / "test_metrics.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    coverage_file.unlink(missing_ok=True)
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
