"""Independent deterministic agent example; no model call, booking, or email."""
import argparse
import hashlib
import os
from sentinel.client import SentinelClient, SentinelError
from sentinel.trace_recorder import TraceRecorder


def classify_ticket(topic, severity):
    if severity not in ("low", "normal", "high"):
        raise ValueError("Unsupported severity.")
    return {"queue": "billing" if topic == "billing" else "technical",
            "priority": "urgent" if severity == "high" else "standard"}


def integrate(developer, worker, *, idempotency_key, topic, severity, slug="support_triage"):
    developer_identity, worker_identity = developer.identity(), worker.identity()
    if developer_identity["organization_id"] != worker_identity["organization_id"]:
        raise ValueError("Developer and worker must belong to the same organization.")
    outcome = classify_ticket(topic, severity)
    agent = developer.register_agent(slug, "Support triage", "Independent deterministic read-only support classifier.")
    version = developer.create_version(agent["agent_id"], "1.0.0",
        "External deterministic classifier. No tools, model calls, bookings, or email.")
    run = developer.create_run(version["agent_version_id"], idempotency_key,
        {"workflow": "external_support_triage", "topic": topic, "severity": severity, "classification": outcome})
    try:
        saved_trace = developer.external_trace(run["run_id"])
    except SentinelError as error:
        if error.status != 404:
            raise
        recorder = TraceRecorder(source="python_support")
        with recorder.span("agent.classify"):
            with recorder.span("tool.route", "tool"):
                pass
        evidence = recorder.finish(outcome, idempotency_key="support-trace-" +
            hashlib.sha256(idempotency_key.encode()).hexdigest())
        saved_trace = worker.submit_external_trace(run["run_id"], evidence)
    completed = worker.complete_run(run["run_id"])
    return {"run_id": completed["run_id"], "status": completed["status"],
            "trace_id": saved_trace["trace_id"], "classification": outcome}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Stable run idempotency key; not an API credential")
    parser.add_argument("--topic", choices=["billing", "technical"], default="technical")
    parser.add_argument("--severity", choices=["low", "normal", "high"], default="normal")
    args = parser.parse_args()
    url = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000")
    developer = SentinelClient(url, os.environ["SENTINEL_DEVELOPER_API_KEY"])
    worker = SentinelClient(url, os.environ["SENTINEL_WORKER_API_KEY"])
    print(integrate(developer, worker, idempotency_key=args.key, topic=args.topic, severity=args.severity))


if __name__ == "__main__":
    main()
