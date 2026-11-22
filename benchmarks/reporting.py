"""Atomic JSON, CSV, Markdown, and resume-evidence report writers."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False,
                           dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def summary_markdown(report: dict[str, Any]) -> str:
    detection = report["failure_detection"]
    observed = report["latency"]["observed"]
    overhead = report["latency"]["monitoring_overhead"]
    tests = report["tests"]
    scale = report["scale"]
    reliability = report["reliability"]
    cost = report["tokens_and_cost"]["observed"]
    optimized = report["tokens_and_cost"]["optimized"]
    cost_reduction = report["tokens_and_cost"]["optimized_vs_observed"]["estimated_cost_reduction_percent"]
    rows = [
        ("Agent executions", scale["agent_executions"]),
        ("Traces processed", scale["traces_processed"]),
        ("Tool calls monitored", scale["tool_calls_monitored"]),
        ("Failure scenarios", report["dataset"]["failure_scenarios"]),
        ("Failure-detection accuracy", _pct(detection["accuracy"])),
        ("Macro precision", _pct(detection["precision_macro"])),
        ("Macro recall", _pct(detection["recall_macro"])),
        ("Macro F1", _pct(detection["f1_macro"])),
        ("Observed P50 latency", f"{observed['total_ms']['p50']:.3f} ms"),
        ("Observed P95 latency", f"{observed['total_ms']['p95']:.3f} ms"),
        ("Observed P99 latency", f"{observed['total_ms']['p99']:.3f} ms"),
        ("Mean monitoring overhead", f"{overhead['paired_delta_ms']['mean']:.3f} ms / {overhead['mean_percent']:.2f}%"),
        ("Automated unit tests", tests.get("total", "not run")),
        ("Test pass rate", _pct(tests["pass_rate"]) if tests.get("pass_rate") is not None else "not run"),
        ("Backend code coverage", _pct(tests["coverage"]["percent"] / 100) if tests.get("coverage") else "not run"),
        ("Observed synthetic token units", cost["total_tokens"]),
        ("Average synthetic token units/execution", f"{cost['average_tokens_per_execution']:.2f}"),
        ("Observed estimated cost/execution", "$" + cost["estimated_cost_per_execution_usd"]),
        ("Measured reference-workflow cost reduction", f"{cost_reduction:.2f}%"),
        ("Execution success rate under injection", _pct(reliability["success_rate"])),
        ("Recovery rate under injection", _pct(reliability["recovery_rate"])),
    ]
    lines = [
        "# AgentOps Sentinel benchmark summary", "",
        f"Run ID: `{report['run_id']}`  ",
        f"Completed: `{report['completed_at']}`  ",
        f"Dataset SHA-256: `{report['dataset']['sha256']}`  ",
        f"Source-tree SHA-256: `{report['environment']['source_tree_sha256']}`", "",
        "| Metric | Result |", "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in rows)
    lines.extend([
        "", "## Evidence boundaries", "",
        "- Failure cases and provider token usage are controlled synthetic fixtures.",
        "- Baseline and observed arms execute identical agent logic; their paired delta measures monitoring overhead.",
        "- The optimized arm is a measured reference-workflow change using exact-key caching and reduced context. Sentinel does not automatically rewrite agents.",
        "- Estimated cost uses the report's declared synthetic rate card. It is not a provider invoice.",
        "- Results describe this machine and run. They do not establish production-user scale or real-world failure prevalence.",
        "", "## Optimization evidence", "",
        f"Observed used {cost['total_tokens']} synthetic token units and estimated ${cost['estimated_cost_usd']}. ",
        f"The optimized reference workflow used {optimized['total_tokens']} units and estimated ${optimized['estimated_cost_usd']}. ",
        f"The measured estimated-cost change was {cost_reduction:.2f}% reduction.", "",
    ])
    return "\n".join(lines)


def resume_markdown(report: dict[str, Any]) -> str:
    detection = report["failure_detection"]
    scale = report["scale"]
    overhead = report["latency"]["monitoring_overhead"]
    reliability = report["reliability"]
    tests = report["tests"]
    coverage = tests.get("coverage", {}).get("percent") if tests.get("coverage") else None
    metrics = [
        "# Resume metrics supported by benchmark evidence", "",
        f"- Controlled evaluation predictions: {detection['samples']}",
        f"- Failure categories including no-failure control: {len(detection['labels'])}",
        f"- Macro failure-detection F1: {_pct(detection['f1_macro'])}",
        f"- Total benchmark agent executions: {scale['agent_executions']}",
        f"- Concurrent load executions: {scale['concurrent_load_executions']}",
        f"- Total monitored traces: {scale['traces_processed']}",
        f"- Concurrent load throughput: {scale['throughput_executions_per_second']:.2f} executions/second",
        f"- Mean paired monitoring overhead: {overhead['paired_delta_ms']['mean']:.3f} ms ({overhead['mean_percent']:.2f}%)",
        f"- Recovery rate in controlled failure injection: {_pct(reliability['recovery_rate'])}",
        f"- Automated unit tests: {tests.get('total', 'not run')}",
    ]
    if coverage is not None:
        metrics.append(f"- Backend statement coverage: {coverage:.2f}%")
    metrics.extend([
        "", "## Resume bullets", "",
        f"- Built a versioned AI-agent failure-diagnostics benchmark spanning {report['dataset']['failure_categories']} failure categories and {detection['samples']} controlled predictions, measuring {_pct(detection['f1_macro'])} macro F1 with a reproducible confusion matrix.",
        f"- Benchmarked Sentinel instrumentation across {scale['agent_executions']} total executions and {scale['traces_processed']} monitored traces, including a {scale['concurrent_load_executions']}-execution concurrent load at {scale['throughput_executions_per_second']:.2f} executions/second with {overhead['paired_delta_ms']['p95']:.3f} ms P95 paired overhead.",
        f"- Validated reliability across {report['dataset']['failure_scenarios']} controlled failure scenarios with {_pct(reliability['recovery_rate'])} recovery and {_pct(reliability['retry_success_rate'])} retry success, backed by {tests.get('total', 'not run')} passing automated unit tests.",
        "", "All figures above come from `benchmark_results.json`. Synthetic evidence must remain labeled as controlled benchmark evidence.", "",
    ])
    return "\n".join(metrics)


def write_csv(path: Path, report: dict[str, Any]) -> None:
    rows = [
        ("agent_executions", report["scale"]["agent_executions"]),
        ("traces_processed", report["scale"]["traces_processed"]),
        ("failure_scenarios", report["dataset"]["failure_scenarios"]),
        ("failure_detection_accuracy", report["failure_detection"]["accuracy"]),
        ("precision_macro", report["failure_detection"]["precision_macro"]),
        ("recall_macro", report["failure_detection"]["recall_macro"]),
        ("f1_macro", report["failure_detection"]["f1_macro"]),
        ("observed_p50_ms", report["latency"]["observed"]["total_ms"]["p50"]),
        ("observed_p95_ms", report["latency"]["observed"]["total_ms"]["p95"]),
        ("observed_p99_ms", report["latency"]["observed"]["total_ms"]["p99"]),
        ("monitoring_overhead_mean_ms", report["latency"]["monitoring_overhead"]["paired_delta_ms"]["mean"]),
        ("monitoring_overhead_mean_percent", report["latency"]["monitoring_overhead"]["mean_percent"]),
        ("automated_tests", report["tests"].get("total", "")),
        ("test_pass_rate", report["tests"].get("pass_rate", "")),
        ("code_coverage_percent", report["tests"].get("coverage", {}).get("percent", "")),
        ("observed_total_tokens", report["tokens_and_cost"]["observed"]["total_tokens"]),
        ("observed_estimated_cost_per_execution_usd", report["tokens_and_cost"]["observed"]["estimated_cost_per_execution_usd"]),
        ("estimated_cost_reduction_percent", report["tokens_and_cost"]["optimized_vs_observed"]["estimated_cost_reduction_percent"]),
        ("execution_success_rate", report["reliability"]["success_rate"]),
        ("recovery_rate", report["reliability"]["recovery_rate"]),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False,
                           dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
        writer = csv.writer(handle); writer.writerow(("metric", "value")); writer.writerows(rows)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_reports(directory: Path, report: dict[str, Any]) -> None:
    write_json(directory / "benchmark_results.json", report)
    write_csv(directory / "benchmark_results.csv", report)
    _atomic_text(directory / "benchmark_summary.md", summary_markdown(report))
    _atomic_text(directory / "resume_metrics.md", resume_markdown(report))
