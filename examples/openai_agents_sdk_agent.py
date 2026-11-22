"""OpenAI Agents SDK integration; offline mode needs no model credential."""
import argparse
import os

from agents import (
    Agent, RunConfig, Runner, agent_span, function_span, generation_span, guardrail_span,
    set_trace_processors, trace,
)
from agents.testing import ScriptedModel, assistant_message
from agents.usage import Usage

from sentinel.client import SentinelClient, SentinelError
from sentinel.integrations.openai_agents_trace import SentinelOpenAIAgentsProcessor


def sanitized_classification(value):
    classification = str(value).strip().lower()
    allowed = {f"{category}:{priority}": {"category": category,
        "priority": priority} for category in ("billing", "technical")
        for priority in ("urgent", "standard")}
    if classification not in allowed:
        raise ValueError("Live agent returned an unsupported classification.")
    return allowed[classification]


def execute(mode="offline", *, task="Classify this support request", model=None):
    processor = SentinelOpenAIAgentsProcessor()
    set_trace_processors([processor])
    try:
        with trace("sentinel_external_openai_agents") as sdk_trace:
            if mode == "live":
                if not os.environ.get("OPENAI_API_KEY"):
                    raise ValueError("OPENAI_API_KEY is required for live mode.")
                if not model:
                    raise ValueError("Supply --model explicitly for live mode.")
                agent = Agent(name="Support classifier", model=model,
                    instructions=("Classify the request. Return exactly one of: "
                                  "billing:urgent, billing:standard, technical:urgent, "
                                  "technical:standard. Do not use tools."))
                output = sanitized_classification(Runner.run_sync(agent, task,
                    run_config=RunConfig(trace_include_sensitive_data=False)).final_output)
                status = "succeeded"
            else:
                with agent_span("support_classifier"):
                    if mode == "failed":
                        failed = generation_span(input=[], output=[], model="offline-fixture")
                        failed.start()
                        failed.set_error({"message": "offline failure", "data": None})
                        failed.finish()
                        output, status = {"error_code": "execution_failed"}, "failed"
                    elif mode == "interrupted":
                        with guardrail_span("human_review", triggered=True):
                            pass
                        output, status = {"status": "interrupted"}, "needs_review"
                    else:
                        scripted = ScriptedModel(
                            [[assistant_message("technical:standard")]], emit_traces=True,
                            default_usage=Usage(requests=1, input_tokens=8,
                                                output_tokens=3, total_tokens=11))
                        offline_agent = Agent(name="Offline support classifier", model=scripted,
                            instructions="Return the deterministic scripted classification.")
                        result = Runner.run_sync(offline_agent, task)
                        scripted.assert_complete()
                        with function_span("classify_ticket", input="discarded",
                                           output="discarded"):
                            pass
                        if result.final_output != "technical:standard":
                            raise RuntimeError("Unexpected scripted agent output.")
                        output = {"category": "technical", "priority": "standard"}
                        status = "succeeded"
        evidence = processor.finish(output, trace_id=sdk_trace.trace_id,
            reported_status=status, idempotency_key=f"openai-agents-trace-{mode}")
        return evidence, output
    finally:
        set_trace_processors([])


def integrate(developer, worker, *, idempotency_key, mode="offline", model=None,
              task="Classify this support request", dataset_id=None,
              slug="sentinel_openai_agents_example"):
    if developer.identity()["organization_id"] != worker.identity()["organization_id"]:
        raise ValueError("Developer and worker must belong to the same organization.")
    agent = developer.register_agent(slug, "OpenAI Agents SDK example",
        "Independent OpenAI Agents SDK path using a privacy-minimal trace processor.")
    version = developer.create_version(agent["agent_id"], "1.0.0",
        "Classify support work without performing external writes.")
    run = developer.create_run(version["agent_version_id"], idempotency_key,
        {"workflow": "external_openai_agents", "scenario": mode})
    try:
        saved = developer.external_trace(run["run_id"])
    except SentinelError as error:
        if error.status != 404:
            raise
        evidence, output = execute(mode, task=task, model=model)
        saved = worker.submit_external_trace(run["run_id"], evidence)
        if evidence["reported_status"] == "succeeded":
            worker.complete_run(run["run_id"])
        evaluation = (developer.evaluate(dataset_id,
            f"openai-agents-evaluation-{idempotency_key}", {"agent-run": run["run_id"]})
            if dataset_id else None)
        return {"run_id": run["run_id"], "trace_id": saved["trace_id"],
                "reported_status": evidence["reported_status"], "output": output,
                "evaluation": evaluation}
    return {"run_id": run["run_id"], "trace_id": saved["trace_id"],
            "reported_status": saved["reported_status"], "replayed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Stable run idempotency key")
    parser.add_argument("--mode", choices=["offline", "live", "failed", "interrupted"],
                        default="offline")
    parser.add_argument("--model", help="Explicit OpenAI model name for live mode")
    parser.add_argument("--task", default="Classify this support request",
                        help="Agent input; it is sent to the provider but not stored by Sentinel")
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    url = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000")
    result = integrate(
        SentinelClient(url, os.environ["SENTINEL_DEVELOPER_API_KEY"]),
        SentinelClient(url, os.environ["SENTINEL_WORKER_API_KEY"]),
        idempotency_key=args.key, mode=args.mode, model=args.model, task=args.task,
        dataset_id=args.dataset_id)
    print(result)


if __name__ == "__main__":
    main()
