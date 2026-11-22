"""Sequential native release checks. A passing report is local evidence only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic, sleep
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / ".local" / "release-checks" / "latest.json"
PRODUCTION_REQUIREMENTS = [
    "Connected-browser interaction and accessibility evidence",
    "Independent outside-developer installation and usefulness pilot",
    "Chosen hosted environment, live provider trials and offsite recovery rehearsal",
]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save_report(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_name("report-" + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(temporary, REPORT)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 9:
                    raise
                # Windows readers/scanners can briefly hold the destination.
                # Preserve atomic replacement; never truncate a passing report.
                sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def frontend_commands():
    # Run npm's JavaScript entry point directly, avoiding shell quoting and
    # implicit npx downloads. Existing dependencies must already be installed.
    candidates = sorted((ROOT / ".local").glob("node-*-win-x64/node.exe"), reverse=True)
    node = str(candidates[0]) if candidates else shutil.which("node")
    if not node:
        raise RuntimeError("Node is not installed.")
    npm_cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if npm_cli.is_file():
        npm = [node, str(npm_cli)]
    elif os.name != "nt" and shutil.which("npm"):
        npm = [shutil.which("npm")]
    else:
        raise RuntimeError("npm is not installed alongside Node.")
    compiler = ROOT / "web" / "node_modules" / "typescript" / "bin" / "tsc"
    if not compiler.is_file():
        raise RuntimeError("Install frontend dependencies before running checks.")
    return [
        ("frontend_types", [node, str(compiler), "--noEmit"], ROOT / "web"),
        ("frontend_lint", npm + ["run", "lint"], ROOT / "web"),
        ("frontend_build", npm + ["run", "build"], ROOT / "web"),
    ]


def plan(profile):
    python = sys.executable
    stages = [("unit", [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], ROOT)]
    if profile == "full":
        stages.extend(frontend_commands())
    if profile in ("native", "full"):
        stages.append(("install_readiness", [python, str(ROOT / "scripts" / "install_check.py")], ROOT))
        for name, filename in [
            ("migration_concurrency", "acceptance_migrations.py"),
            ("adapter_limits", "acceptance_adapters_limits.py"),
            ("native_calendar", "acceptance_calendar.py"),
            ("website_enquiries", "acceptance_enquiries.py"),
            ("access_client", "acceptance_access_client.py"),
            ("evaluations", "acceptance_evaluations.py"),
            ("external_traces", "acceptance_external_traces.py"),
            ("telemetry", "acceptance_telemetry.py"),
            ("advanced_evaluations", "acceptance_advanced_evaluations.py"),
            ("product_operations", "acceptance_product_operations.py"),
            ("mcp_stdio", "acceptance_mcp.py"),
            ("api_recovery", "integration_api.py"),
        ]:
            stages.append((name, [python, str(ROOT / "tests" / filename)], ROOT))
        if profile == "full":
            stages.extend([
                ("security_lab", [python, str(ROOT / "scripts" / "security_lab.py")], ROOT),
                ("failure_lab", [python, str(ROOT / "scripts" / "failure_lab.py")], ROOT),
                ("capacity", [python, str(ROOT / "scripts" / "capacity_check.py")], ROOT),
                ("native_service", [python, str(ROOT / "tests" / "acceptance_local_service.py")], ROOT),
            ])
            stages.append(("pilot_startup", [python, str(ROOT / "scripts" / "pilot.py"), "--check", "--demo",
                                            "--api-port", "8050", "--booking-port", "8052", "--web-port", "3050"], ROOT))
        stages.append(("backup_restore", [python, str(ROOT / "scripts" / "backup_database.py"), "check"], ROOT))
    return stages


def execute(stages, report, run=subprocess.run, persist=save_report):
    report["stages"] = [{"name": name, "status": "not_run"} for name, _, _ in stages]
    persist(report)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    # Native checks and frontend builds run sequentially to avoid contention.
    # Do not save raw subprocess output: failures may contain fixture payloads.
    for entry, (_, command, cwd) in zip(report["stages"], stages):
        entry.update(status="running", started_at=timestamp())
        persist(report)
        print(f"Checking {entry['name']}...", flush=True)
        started = monotonic()
        try:
            stage_environment = environment.copy()
            stage_environment["PATH"] = str(Path(command[0]).resolve().parent) + os.pathsep + environment.get("PATH", "")
            outcome = run(command, cwd=cwd, env=stage_environment,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          check=False)
        except (OSError, KeyboardInterrupt) as error:
            entry.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                         error_type=type(error).__name__, finished_at=timestamp())
            report["status"] = entry["status"]
            persist(report)
            return False
        entry.update(status="passed" if outcome.returncode == 0 else "failed",
                     exit_code=outcome.returncode,
                     duration_seconds=round(monotonic() - started, 3),
                     finished_at=timestamp())
        persist(report)
        if outcome.returncode != 0:
            report["status"] = "failed"
            persist(report)
            print(f"Failed: {entry['name']}. Rerun its documented command for diagnostics.", flush=True)
            return False
        print(f"Passed: {entry['name']}", flush=True)
    report["status"] = "passed"
    persist(report)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("unit", "native", "full"), default="full",
                        help="full includes frontend and native PostgreSQL acceptance")
    args = parser.parse_args()
    report = {"schema_version": 2, "run_id": uuid4().hex, "started_at": timestamp(),
              "profile": args.profile, "status": "running", "stages": [],
              "release_scope": "local_pilot", "automated_release_ready": False,
              "local_release_ready": False,
              "production_ready": False, "production_requirements": PRODUCTION_REQUIREMENTS}
    save_report(report)
    try:
        passed = execute(plan(args.profile), report)
    except RuntimeError as error:
        # Preflight messages are authored above and contain no configuration.
        report.update(status="failed", preflight_error=str(error))
        print(str(error), flush=True)
        passed = False
    report["finished_at"] = timestamp()
    report["automated_release_ready"] = bool(passed and args.profile == "full")
    save_report(report)
    print("Report: .local/release-checks/latest.json", flush=True)
    print("Local checks do not certify production readiness.", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
