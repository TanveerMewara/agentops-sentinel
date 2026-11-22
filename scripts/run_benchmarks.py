"""Run the reproducible AgentOps Sentinel benchmark and generate all evidence reports."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from benchmarks.metrics import classification_metrics, distribution, percent_change
from benchmarks.reporting import write_reports
from benchmarks.workloads import (
    aggregate_reliability, cost_summary, execute_scenario, load_scenarios,
    run_concurrent_load,
)
from sentinel.failure_diagnostics import DETECTOR_VERSION, FAILURE_CATEGORIES


def source_tree_hash() -> str:
    digest = hashlib.sha256()
    roots = (ROOT / "src", ROOT / "benchmarks", ROOT / "scripts", ROOT / "tests")
    files = []
    for base in roots:
        files.extend(path for path in base.rglob("*") if path.is_file() and
                     path.suffix in {".py", ".sql"} and "__pycache__" not in path.parts)
    files.extend(path for path in (ROOT / "datasets").glob("*.json") if path.is_file())
    for path in sorted(files, key=lambda item: item.as_posix()):
        relative = path.relative_to(ROOT).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big")); digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    return digest.hexdigest()


def physical_memory_bytes() -> int | None:
    if os.name == "nt":
        try:
            import ctypes
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                            ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                            ("available_extended", ctypes.c_ulonglong)]
            status = MemoryStatus(); status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.total_physical)
        except (AttributeError, OSError):
            return None
    return None


def environment() -> dict[str, object]:
    return {
        "os": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER") or "unavailable",
        "logical_cpu_count": os.cpu_count(), "physical_memory_bytes": physical_memory_bytes(),
        "python": platform.python_version(), "python_implementation": platform.python_implementation(),
        "source_tree_sha256": source_tree_hash(), "git_commit": None,
        "git_note": "Workspace has no Git metadata; source-tree hash identifies measured code.",
    }


def run_tests() -> dict[str, object]:
    command = [sys.executable, str(ROOT / "scripts" / "run_test_metrics.py")]
    result = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    target = ROOT / "reports" / "test_metrics.json"
    if result.returncode != 0 or not target.is_file():
        raise RuntimeError("Automated tests or coverage failed; run scripts/run_test_metrics.py for details.")
    report = json.loads(target.read_text(encoding="utf-8"))
    if not report.get("successful"):
        raise RuntimeError("Automated tests did not pass.")
    return report


def arm_latency(records):
    return {
        "total_ms": distribution([item["total_ms"] for item in records]),
        "model_total_ms": distribution([item["model_ms"] for item in records]),
        "individual_model_call_ms": distribution([
            value for item in records for value in item["model_call_latencies_ms"]]),
        "tool_total_ms": distribution([item["tool_ms"] for item in records]),
        "individual_tool_call_ms": distribution([
            value for item in records for value in item["tool_call_latencies_ms"]]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=10,
                        help="Measured repetitions of every labeled scenario per arm (default: 10).")
    parser.add_argument("--load-executions", type=int, default=240)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--skip-tests", action="store_true",
                        help="Reuse reports/test_metrics.json instead of rerunning tests and coverage.")
    args = parser.parse_args()
    if not 3 <= args.repetitions <= 100:
        raise SystemExit("Use 3-100 scenario repetitions.")
    if not 20 <= args.load_executions <= 5000 or not 1 <= args.concurrency <= 64:
        raise SystemExit("Use 20-5000 load executions and concurrency 1-64.")

    tests_path = ROOT / "reports" / "test_metrics.json"
    if args.skip_tests:
        if not tests_path.is_file():
            raise SystemExit("No test metrics report exists; run without --skip-tests first.")
        tests = json.loads(tests_path.read_text(encoding="utf-8"))
        if not tests.get("successful"):
            raise SystemExit("Saved test metrics are not passing.")
    else:
        tests = run_tests()

    dataset_path = ROOT / "datasets" / "failure-detection-v1.json"
    scenarios, dataset_hash = load_scenarios(dataset_path)
    expected_labels = {scenario.ground_truth for scenario in scenarios}
    if expected_labels != set(FAILURE_CATEGORIES):
        raise SystemExit("The dataset must cover every declared category and no-failure controls.")

    model_delay = 0.0006; tool_delay = 0.0004
    # Warm up interpreter, validators, and clocks. Warm-up data is never reported.
    for arm in ("baseline", "observed", "optimized"):
        for scenario in scenarios[:3]:
            execute_scenario(scenario, arm, model_delay_seconds=model_delay,
                             tool_delay_seconds=tool_delay)

    baseline = []; observed = []; optimized = []; paired_deltas = []
    for repetition in range(args.repetitions):
        for scenario in scenarios:
            # Alternate order to reduce systematic warm-cache bias in the paired comparison.
            if repetition % 2:
                observed_item = execute_scenario(scenario, "observed", model_delay_seconds=model_delay,
                                                 tool_delay_seconds=tool_delay)
                baseline_item = execute_scenario(scenario, "baseline", model_delay_seconds=model_delay,
                                                 tool_delay_seconds=tool_delay)
            else:
                baseline_item = execute_scenario(scenario, "baseline", model_delay_seconds=model_delay,
                                                 tool_delay_seconds=tool_delay)
                observed_item = execute_scenario(scenario, "observed", model_delay_seconds=model_delay,
                                                 tool_delay_seconds=tool_delay)
            optimized_item = execute_scenario(scenario, "optimized", model_delay_seconds=model_delay,
                                              tool_delay_seconds=tool_delay)
            baseline.append(baseline_item); observed.append(observed_item); optimized.append(optimized_item)
            paired_deltas.append(observed_item["total_ms"] - baseline_item["total_ms"])

    expected = [item["ground_truth"] for item in observed]
    predicted = [item["prediction"] for item in observed]
    classification = classification_metrics(expected, predicted, FAILURE_CATEGORIES)
    classification.update({
        "detector_version": DETECTOR_VERSION,
        "misclassifications": [
            {"scenario_id": item["scenario_id"], "expected": item["ground_truth"],
             "predicted": item["prediction"]}
            for item in observed if item["ground_truth"] != item["prediction"]
        ],
        "detection_latency_ms": distribution([item["detection_ms"] for item in observed]),
    })

    baseline_latency = arm_latency(baseline); observed_latency = arm_latency(observed)
    optimized_latency = arm_latency(optimized)
    overhead = {
        "method": "paired observed total latency minus identical baseline total latency",
        "paired_delta_ms": distribution(paired_deltas),
        "mean_percent": percent_change(baseline_latency["total_ms"]["mean"],
                                       observed_latency["total_ms"]["mean"]),
        "negative_samples_retained": sum(value < 0 for value in paired_deltas),
    }
    input_rate = Decimal("0.50"); output_rate = Decimal("1.50")
    observed_cost = cost_summary(observed, input_rate, output_rate)
    optimized_cost = cost_summary(optimized, input_rate, output_rate)
    baseline_cost = cost_summary(baseline, input_rate, output_rate)
    observed_cost_value = Decimal(observed_cost["estimated_cost_usd"])
    optimized_cost_value = Decimal(optimized_cost["estimated_cost_usd"])
    cost_reduction = ((observed_cost_value - optimized_cost_value) / observed_cost_value * 100
                      if observed_cost_value else Decimal(0))

    load = run_concurrent_load(scenarios, args.load_executions, args.concurrency,
                               model_delay, tool_delay)
    monitored = len(observed) + len(optimized) + args.load_executions
    scale = {
        **load,
        "agent_executions": len(baseline) + monitored,
        "concurrent_load_executions": args.load_executions,
        "monitored_agent_executions": monitored,
        "baseline_agent_executions": len(baseline),
        "traces_processed": len(observed) + len(optimized) + load["traces_processed"],
        "spans_processed": (sum(item["trace_spans"] for item in observed + optimized)
                            + load["spans_processed"]),
        "tool_calls_monitored": (sum(item["tool_calls_observed"] for item in observed + optimized)
                                 + load["tool_calls_monitored"]),
        "evaluation_runs": len(observed),
        "failure_scenario_evaluations": sum(item["ground_truth"] != "no_failure" for item in observed),
    }
    reliability = aggregate_reliability(observed)
    report = {
        "schema_version": 1, "run_id": uuid.uuid4().hex,
        "started_at": tests.get("completed_at"), "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed", "environment": environment(),
        "configuration": {
            "repetitions_per_scenario": args.repetitions, "warmup_scenarios_per_arm": 3,
            "load_executions": args.load_executions, "concurrency": args.concurrency,
            "model_delay_seconds": model_delay, "tool_delay_seconds": tool_delay,
            "baseline_definition": "deterministic workflow without Sentinel instrumentation",
            "observed_definition": "identical workflow with TraceRecorder and structured failure diagnosis",
            "optimized_definition": "observed workflow plus exact-key model-call cache and reduced repeated context",
        },
        "dataset": {
            "path": "datasets/failure-detection-v1.json", "sha256": dataset_hash,
            "unique_scenarios": len(scenarios),
            "failure_scenarios": sum(item.ground_truth != "no_failure" for item in scenarios),
            "success_controls": sum(item.ground_truth == "no_failure" for item in scenarios),
            "failure_categories": len(FAILURE_CATEGORIES) - 1,
            "labels": list(FAILURE_CATEGORIES), "evidence_type": "controlled_synthetic_structured",
        },
        "failure_detection": classification,
        "latency": {"unit": "milliseconds", "baseline": baseline_latency,
                    "observed": observed_latency, "optimized": optimized_latency,
                    "monitoring_overhead": overhead,
                    "raw_samples": {
                        "baseline_total_ms": [round(item["total_ms"], 6) for item in baseline],
                        "observed_total_ms": [round(item["total_ms"], 6) for item in observed],
                        "optimized_total_ms": [round(item["total_ms"], 6) for item in optimized],
                        "paired_overhead_ms": [round(value, 6) for value in paired_deltas],
                        "detection_ms": [round(item["detection_ms"], 6) for item in observed],
                    }},
        "tests": tests, "scale": scale,
        "tokens_and_cost": {
            "measurement_boundary": "Synthetic provider reports deterministic token units; cost uses the declared benchmark rate card.",
            "baseline": baseline_cost, "observed": observed_cost, "optimized": optimized_cost,
            "optimized_vs_observed": {
                "token_reduction_percent": round((1 - optimized_cost["total_tokens"] / observed_cost["total_tokens"]) * 100, 6),
                "estimated_cost_reduction_percent": round(float(cost_reduction), 6),
                "model_calls_avoided": sum(item["model_calls"] for item in observed) - sum(item["model_calls"] for item in optimized),
            }},
        "reliability": reliability,
        "before_vs_after": {
            "baseline": {"monitoring": False, "optimization": False,
                         "mean_latency_ms": baseline_latency["total_ms"]["mean"],
                         "failure_detection": "not_available", "success_rate": reliability["success_rate"],
                         "token_usage": baseline_cost["total_tokens"],
                         "estimated_cost_usd": baseline_cost["estimated_cost_usd"],
                         "monitoring_overhead_ms": 0},
            "observed": {"monitoring": True, "optimization": False,
                         "mean_latency_ms": observed_latency["total_ms"]["mean"],
                         "failure_detection_accuracy": classification["accuracy"],
                         "success_rate": reliability["success_rate"], "token_usage": observed_cost["total_tokens"],
                         "estimated_cost_usd": observed_cost["estimated_cost_usd"],
                         "monitoring_overhead_mean_ms": overhead["paired_delta_ms"]["mean"]},
            "optimized": {"monitoring": True, "optimization": True,
                          "mean_latency_ms": optimized_latency["total_ms"]["mean"],
                          "failure_detection_accuracy": classification["accuracy"],
                          "success_rate": reliability["success_rate"], "token_usage": optimized_cost["total_tokens"],
                          "estimated_cost_usd": optimized_cost["estimated_cost_usd"],
                          "monitoring_overhead_mean_ms": None},
            "interpretation": "Monitoring is measured with unchanged behavior. Optimization effects are reported separately.",
        },
        "limitations": [
            "Failure scenarios are controlled synthetic structured evidence, not a sampled production distribution.",
            "The deterministic detector and dataset require external validation before generalization claims.",
            "Synthetic token units and estimated costs are not provider billing evidence.",
            "Local single-machine concurrency does not establish multi-host production capacity.",
            "Unit-suite coverage excludes separate acceptance-script subprocesses and frontend TypeScript.",
        ],
    }
    write_reports(ROOT / "reports", report)
    print(json.dumps({
        "status": report["status"], "run_id": report["run_id"],
        "failure_detection_f1_macro": classification["f1_macro"],
        "observed_p95_ms": observed_latency["total_ms"]["p95"],
        "monitoring_overhead_mean_ms": overhead["paired_delta_ms"]["mean"],
        "tests": tests["total"], "coverage_percent": tests["coverage"]["percent"],
        "report": "reports/benchmark_results.json",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
