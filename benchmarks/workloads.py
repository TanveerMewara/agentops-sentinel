"""Controlled workloads for paired monitoring and reliability measurements."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from sentinel.failure_diagnostics import FailureObservation, diagnose
from sentinel.trace_recorder import TraceRecorder

from .metrics import distribution


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    ground_truth: str
    observation: FailureObservation
    outcome: dict[str, Any]


def load_scenarios(path: Path) -> tuple[list[Scenario], str]:
    raw = path.read_bytes()
    body = json.loads(raw)
    if body.get("schema_version") != 1 or body.get("dataset_id") != "failure-detection-v1":
        raise ValueError("Unsupported failure benchmark dataset.")
    scenarios = []
    identifiers = set()
    for item in body.get("scenarios", []):
        identifier = item.get("id")
        if not isinstance(identifier, str) or identifier in identifiers:
            raise ValueError("Scenario identifiers must be unique strings.")
        identifiers.add(identifier)
        observation = FailureObservation.from_mapping(item.get("observation", {}))
        outcome = item.get("outcome")
        required = {"successful", "retry_attempted", "retry_succeeded", "recovery_attempted",
                    "recovered", "tool_calls", "tool_failures"}
        if not isinstance(outcome, dict) or set(outcome) != required:
            raise ValueError("Each scenario needs a complete reliability outcome.")
        for name in required - {"tool_calls", "tool_failures"}:
            if type(outcome[name]) is not bool:
                raise ValueError("Reliability outcome flags must be booleans.")
        if any(type(outcome[name]) is not int or outcome[name] < 0
               for name in ("tool_calls", "tool_failures")):
            raise ValueError("Tool counts must be non-negative integers.")
        if outcome["tool_failures"] > outcome["tool_calls"]:
            raise ValueError("Tool failures cannot exceed tool calls.")
        scenarios.append(Scenario(identifier, item.get("ground_truth"), observation, outcome))
    if not scenarios:
        raise ValueError("Failure benchmark dataset is empty.")
    return scenarios, hashlib.sha256(raw).hexdigest()


def _wait(seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        pass


def _token_count(value: str) -> int:
    """Synthetic-provider token units; not presented as a real tokenizer result."""
    return len(value.split())


def _model_call(scenario: Scenario, prompt: str, delay_seconds: float) -> tuple[dict[str, str], int, int, float]:
    started = time.perf_counter_ns()
    hashlib.sha256(prompt.encode()).digest()
    _wait(delay_seconds)
    output = {"decision": "continue", "scenario": scenario.scenario_id}
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    return output, _token_count(prompt), _token_count(json.dumps(output)), elapsed


def _tool_call(scenario: Scenario, delay_seconds: float) -> tuple[dict[str, str], float]:
    started = time.perf_counter_ns()
    hashlib.sha256(scenario.scenario_id.encode()).digest()
    _wait(delay_seconds)
    return {"status": "bounded_fixture"}, (time.perf_counter_ns() - started) / 1_000_000


def execute_scenario(scenario: Scenario, arm: str, *, model_delay_seconds: float,
                     tool_delay_seconds: float) -> dict[str, Any]:
    if arm not in ("baseline", "observed", "optimized"):
        raise ValueError("Unknown benchmark arm.")
    started = time.perf_counter_ns()
    recorder = TraceRecorder(source="benchmark_agent") if arm != "baseline" else None
    context = ("You are a bounded benchmark agent. Use only supplied structured evidence. "
               "Never infer private content. Return the deterministic decision. ") * 4
    if arm == "optimized":
        context = "Use supplied structured evidence. Return the deterministic decision."
    prompt = f"{context} scenario {scenario.scenario_id}"

    model_ms: list[float] = []
    tool_ms: list[float] = []
    input_tokens = output_tokens = 0

    def model_once():
        nonlocal input_tokens, output_tokens
        if recorder:
            with recorder.span("model.generate", "model") as span:
                output, in_tokens, out_tokens, elapsed = _model_call(
                    scenario, prompt, model_delay_seconds)
                span["input_tokens"], span["output_tokens"] = in_tokens, out_tokens
        else:
            output, in_tokens, out_tokens, elapsed = _model_call(scenario, prompt, model_delay_seconds)
        input_tokens += in_tokens; output_tokens += out_tokens; model_ms.append(elapsed)
        return output

    first = model_once()
    if arm == "optimized":
        second = first  # exact-key deterministic cache hit
    else:
        second = model_once()
    if recorder:
        with recorder.span("tool.execute", "tool"):
            tool_result, elapsed = _tool_call(scenario, tool_delay_seconds)
    else:
        tool_result, elapsed = _tool_call(scenario, tool_delay_seconds)
    tool_ms.append(elapsed)

    prediction = None
    detection_ms = 0.0
    if recorder:
        detection_started = time.perf_counter_ns()
        with recorder.span("sentinel.detect", "agent"):
            prediction = diagnose(scenario.observation).category
        detection_ms = (time.perf_counter_ns() - detection_started) / 1_000_000
        trace = recorder.finish(
            {"result": second["decision"], "tool_status": tool_result["status"]},
            reported_status="succeeded" if scenario.outcome["successful"] else "failed",
            idempotency_key=f"benchmark-{arm}-{scenario.scenario_id}-{time.perf_counter_ns()}",
        )
    else:
        trace = None
    total_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "scenario_id": scenario.scenario_id, "ground_truth": scenario.ground_truth,
        "prediction": prediction, "total_ms": total_ms, "model_ms": sum(model_ms),
        "model_call_latencies_ms": model_ms, "tool_ms": sum(tool_ms),
        "tool_call_latencies_ms": tool_ms, "detection_ms": detection_ms,
        "model_calls": len(model_ms), "tool_calls_observed": 1,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "trace_spans": len(trace["spans"]) if trace else 0,
        "trace_generated": trace is not None, "outcome": scenario.outcome,
    }


def aggregate_reliability(records: list[dict[str, Any]]) -> dict[str, float | int]:
    outcomes = [record["outcome"] for record in records]
    executions = len(outcomes)
    successes = sum(item["successful"] for item in outcomes)
    retries = [item for item in outcomes if item["retry_attempted"]]
    recoveries = [item for item in outcomes if item["recovery_attempted"]]
    tool_calls = sum(item["tool_calls"] for item in outcomes)
    tool_failures = sum(item["tool_failures"] for item in outcomes)
    return {
        "executions": executions, "successful_executions": successes,
        "failed_executions": executions - successes,
        "success_rate": round(successes / executions, 6),
        "failure_rate": round((executions - successes) / executions, 6),
        "retry_attempts": len(retries),
        "retry_success_rate": round(sum(item["retry_succeeded"] for item in retries) / len(retries), 6) if retries else 0,
        "recovery_attempts": len(recoveries),
        "recovery_rate": round(sum(item["recovered"] for item in recoveries) / len(recoveries), 6) if recoveries else 0,
        "mean_failures_per_execution": round(sum(not item["successful"] for item in outcomes) / executions, 6),
        "tool_calls": tool_calls, "tool_successes": tool_calls - tool_failures,
        "tool_failures": tool_failures,
        "tool_success_rate": round((tool_calls - tool_failures) / tool_calls, 6) if tool_calls else 0,
        "tool_failure_rate": round(tool_failures / tool_calls, 6) if tool_calls else 0,
    }


def cost_summary(records: list[dict[str, Any]], input_rate: Decimal,
                 output_rate: Decimal) -> dict[str, Any]:
    input_tokens = sum(record["input_tokens"] for record in records)
    output_tokens = sum(record["output_tokens"] for record in records)
    total = input_tokens + output_tokens
    cost = (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)
    successes = sum(record["outcome"]["successful"] for record in records)
    return {
        "evidence": "deterministic_synthetic_provider_usage",
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total,
        "average_tokens_per_execution": round(total / len(records), 6),
        "estimated_cost_usd": str(cost.quantize(Decimal("0.00000001"))),
        "estimated_cost_per_execution_usd": str((cost / len(records)).quantize(Decimal("0.00000001"))),
        "estimated_cost_per_successful_task_usd": (
            str((cost / successes).quantize(Decimal("0.00000001"))) if successes else None),
        "rate_card_usd_per_million": {"input": str(input_rate), "output": str(output_rate)},
    }


def run_concurrent_load(scenarios: list[Scenario], executions: int, concurrency: int,
                        model_delay_seconds: float, tool_delay_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        records = list(pool.map(
            lambda index: execute_scenario(
                scenarios[index % len(scenarios)], "observed",
                model_delay_seconds=model_delay_seconds, tool_delay_seconds=tool_delay_seconds),
            range(executions),
        ))
    elapsed = time.perf_counter() - started
    return {
        "simulated_concurrent_agents": concurrency, "agent_executions": executions,
        "duration_seconds": round(elapsed, 6),
        "throughput_executions_per_second": round(executions / elapsed, 6),
        "throughput_traces_per_second": round(sum(record["trace_generated"] for record in records) / elapsed, 6),
        "throughput_spans_per_second": round(sum(record["trace_spans"] for record in records) / elapsed, 6),
        "throughput_tool_calls_per_second": round(sum(record["tool_calls_observed"] for record in records) / elapsed, 6),
        "traces_processed": sum(record["trace_generated"] for record in records),
        "spans_processed": sum(record["trace_spans"] for record in records),
        "tool_calls_monitored": sum(record["tool_calls_observed"] for record in records),
        "latency_ms": distribution([record["total_ms"] for record in records]),
    }
