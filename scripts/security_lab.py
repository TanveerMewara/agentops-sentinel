"""Local scripted boundary checks. Passing is not a general security score."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
REPORT = ROOT / ".local" / "security-lab" / "latest.json"
GROUPS = {
    "hostile_decisions": ("test_security_boundaries",),
    "response_redaction": ("test_http_security",),
    "calendar_permissions": ("test_calendar", "test_calendar_desk", "test_calendar_workflow"),
    "approval_semantics_lesson": ("test_action_approvals",),
    "adapter_contract_isolation": ("test_adapters",),
    "client_transport": ("test_client_access", "test_client_network"),
    "read_only_mcp": ("test_mcp_stdio",),
}
GAPS = [
    "Hosted-model prompt-injection success rates and representative attacks",
    "Connected-browser interaction, accessibility, XSS and remote MCP/OAuth",
    "Full prompt/output/checkpoint/log redaction and downstream exfiltration",
    "Distributed denial-of-service, compromised deployment code, host and database administrators",
]


def safe_identifier(test):
    # unittest subtest IDs interpolate arbitrary parameter values.
    return getattr(test, "test_case", test).id()


def run_checks(groups=GROUPS, loader=None):
    loader = loader or unittest.TestLoader()
    checks = []
    for name, modules in groups.items():
        # Capture runner diagnostics and fixture output in memory, never in reports.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            suite = unittest.TestSuite(loader.loadTestsFromName(module) for module in modules)
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        status = "failing" if not result.wasSuccessful() else "partial" if result.skipped or result.expectedFailures or not result.testsRun else "passing"
        checks.append({"name": name, "status": status, "tests_run": result.testsRun,
            "failures": sorted(set(safe_identifier(test) for test, _ in result.failures)),
            "errors": sorted(set(safe_identifier(test) for test, _ in result.errors)),
            "skipped": sorted(set(safe_identifier(test) for test, _ in result.skipped)),
            "expected_failures": sorted(set(safe_identifier(test) for test, _ in result.expectedFailures)),
            "unexpected_successes": sorted(set(safe_identifier(test) for test in result.unexpectedSuccesses))})
    status = "failing" if any(check["status"] == "failing" for check in checks) else "partial" if not checks or any(check["status"] == "partial" for check in checks) else "passing"
    return {"schema_version": 1, "run_id": uuid4().hex,
        "completed_at": datetime.now(timezone.utc).isoformat(), "status": status,
        "tests_run": sum(check["tests_run"] for check in checks), "groups": checks,
        "security_score": None, "production_ready": False,
        "boundary": "Scripted local regression checks; no universal prompt-injection or data-leakage guarantee.",
        "coverage_gaps": GAPS}


def save_report(report, target=REPORT):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    report = run_checks()
    save_report(report)
    print(f"Security lab: {report['status']} ({report['tests_run']} checks).")
    print("Report: .local/security-lab/latest.json")
    print("Local boundary regression evidence; no production readiness or security score.")
    return 0 if report["status"] == "passing" else 1


if __name__ == "__main__":
    raise SystemExit(main())
