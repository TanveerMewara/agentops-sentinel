"""Runnable LangGraph agent that reports privacy-minimal evidence to Sentinel."""
import argparse
import os

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from sentinel.client import SentinelClient, SentinelError
from sentinel.integrations.langchain_trace import SentinelLangChainCallback


def execute(mode):
    builder = StateGraph(dict)
    if mode == "success":
        builder.add_node("increment", lambda state: {"value": state.get("value", 0) + 1})
        checkpointer = None
    elif mode == "failed":
        def fail(_state):
            raise RuntimeError("Deliberate example failure; exception text is not exported.")
        builder.add_node("fail", fail)
        checkpointer = None
    else:
        builder.add_node("review", lambda _state: interrupt({"type": "human_review"}))
        checkpointer = InMemorySaver()
    node = {"success": "increment", "failed": "fail", "interrupted": "review"}[mode]
    builder.add_edge(START, node)
    builder.add_edge(node, END)
    callback = SentinelLangChainCallback(source="langgraph")
    config = {"callbacks": [callback]}
    if checkpointer is not None:
        config["configurable"] = {"thread_id": "sentinel-example"}
    try:
        result = builder.compile(checkpointer=checkpointer).invoke({"value": 1}, config=config)
    except RuntimeError:
        result = {"error_code": "execution_failed"}
    if mode == "interrupted":
        result = {"status": "interrupted"}
    status = {"success": "succeeded", "failed": "failed",
              "interrupted": "needs_review"}[mode]
    return callback.finish(result, reported_status=status,
                           idempotency_key=f"langgraph-trace-{mode}"), result


def integrate(developer, worker, *, idempotency_key, mode="success", dataset_id=None,
              slug="sentinel_langgraph_example"):
    if developer.identity()["organization_id"] != worker.identity()["organization_id"]:
        raise ValueError("Developer and worker must belong to the same organization.")
    agent = developer.register_agent(slug, "LangGraph external example",
        "Independent LangGraph agent instrumented through Sentinel's callback adapter.")
    version = developer.create_version(agent["agent_id"], "1.0.0",
        "Execute the selected local graph path without external side effects.")
    run = developer.create_run(version["agent_version_id"], idempotency_key,
        {"workflow": "external_langgraph", "scenario": mode})
    try:
        saved = developer.external_trace(run["run_id"])
    except SentinelError as error:
        if error.status != 404:
            raise
        evidence, output = execute(mode)
        saved = worker.submit_external_trace(run["run_id"], evidence)
        if mode == "success":
            worker.complete_run(run["run_id"])
        if dataset_id:
            evaluation = developer.evaluate(dataset_id,
                f"langgraph-evaluation-{idempotency_key}", {"agent-run": run["run_id"]})
        else:
            evaluation = None
        return {"run_id": run["run_id"], "trace_id": saved["trace_id"],
                "reported_status": evidence["reported_status"], "output": output,
                "evaluation": evaluation}
    return {"run_id": run["run_id"], "trace_id": saved["trace_id"],
            "reported_status": saved["reported_status"], "replayed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Stable run idempotency key")
    parser.add_argument("--mode", choices=["success", "failed", "interrupted"],
                        default="success")
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    url = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000")
    result = integrate(
        SentinelClient(url, os.environ["SENTINEL_DEVELOPER_API_KEY"]),
        SentinelClient(url, os.environ["SENTINEL_WORKER_API_KEY"]),
        idempotency_key=args.key, mode=args.mode, dataset_id=args.dataset_id)
    print(result)


if __name__ == "__main__":
    main()
