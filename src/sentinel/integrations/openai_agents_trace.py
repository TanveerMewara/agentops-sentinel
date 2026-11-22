"""Privacy-minimal OpenAI Agents SDK tracing processor for Sentinel evidence."""
import hashlib
import re
from datetime import datetime, timezone
from threading import RLock

from agents.tracing.processor_interface import TracingProcessor

from ..external_traces import ExternalTraceCreate


_KINDS = {
    "agent": "agent", "task": "agent", "turn": "agent", "handoff": "agent",
    "generation": "model", "response": "model",
    "function": "tool", "guardrail": "tool", "computer": "tool",
    "mcp_tools": "tool", "custom": "tool",
}


def _slug(value, fallback):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text or fallback)[:60]


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Framework span timestamps are required.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Framework span timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _usage(data):
    value = getattr(data, "usage", None)
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("input_tokens", value.get("prompt_tokens"))
    output_tokens = value.get("output_tokens", value.get("completion_tokens"))
    if (type(input_tokens) is int and type(output_tokens) is int and
            0 <= input_tokens <= 10000000 and 0 <= output_tokens <= 10000000):
        return input_tokens, output_tokens
    return None


def _name(data_type, data, kind):
    if data_type in ("generation", "response"):
        component = "generate"
    elif data_type == "handoff":
        component = "handoff"
    elif data_type == "turn":
        component = "turn"
    elif data_type == "custom":
        # Custom span names can contain user data, so retain only the structural type.
        component = "custom"
    else:
        component = getattr(data, "name", None) or data_type
    return f"{kind}.{_slug(component, data_type)}"


class SentinelOpenAIAgentsProcessor(TracingProcessor):
    """Collect SDK span structure without prompts, outputs, arguments or errors."""

    def __init__(self, source="openai_agents"):
        self.source = source
        self._traces = {}
        self._lock = RLock()

    def on_trace_start(self, trace):
        try:
            with self._lock:
                self._traces.setdefault(trace.trace_id, {
                    "started_at": datetime.now(timezone.utc), "ended": False,
                    "active": set(), "spans": [], "overflow": False,
                    "invalid": False, "finished": False,
                })
        except Exception:
            return

    def on_trace_end(self, trace):
        try:
            with self._lock:
                state = self._traces.get(trace.trace_id)
                if state is not None:
                    state["ended"] = True
        except Exception:
            return

    def on_span_start(self, span):
        try:
            with self._lock:
                state = self._traces.get(span.trace_id)
                if state is not None:
                    state["active"].add(span.span_id)
        except Exception:
            return

    def on_span_end(self, span):
        try:
            with self._lock:
                state = self._traces.get(span.trace_id)
                if state is None:
                    return
                state["active"].discard(span.span_id)
                data = span.span_data
                data_type = getattr(data, "type", "")
                kind = _KINDS.get(data_type)
                if kind is None:
                    return
                if len(state["spans"]) >= 100:
                    state["overflow"] = True
                    return
                started, ended = _timestamp(span.started_at), _timestamp(span.ended_at)
                if ended < started:
                    state["invalid"] = True
                    return
                usage = _usage(data) if kind == "model" else None
                status = "failed" if span.error is not None else "completed"
                if data_type == "guardrail" and getattr(data, "triggered", False):
                    status = "needs_review"
                state["spans"].append({
                    "raw_id": span.span_id, "raw_parent": span.parent_id,
                    "started": started, "ended": ended,
                    "name": _name(data_type, data, kind), "kind": kind,
                    "status": status, "usage": usage,
                })
        except Exception:
            try:
                with self._lock:
                    state = self._traces.get(getattr(span, "trace_id", None))
                    if state is not None:
                        state["invalid"] = True
            except Exception:
                return

    def shutdown(self):
        return None

    def force_flush(self):
        return None

    def trace_ids(self):
        with self._lock:
            return tuple(self._traces)

    def finish(self, output, *, trace_id=None, reported_status="succeeded",
               idempotency_key=None):
        with self._lock:
            available = [key for key, state in self._traces.items()
                         if state["ended"] and not state["finished"]]
            selected = trace_id or (available[0] if len(available) == 1 else None)
            if selected is None or selected not in self._traces:
                raise ValueError("Select exactly one completed OpenAI Agents SDK trace.")
            state = self._traces[selected]
            if state["finished"]:
                raise ValueError("This framework trace is already finalized.")
            if not state["ended"] or state["active"]:
                raise ValueError("Finalize only after the framework trace and spans have closed.")
            if state["overflow"]:
                raise ValueError("Trace exceeds the 100-span evidence limit.")
            if state["invalid"] or not state["spans"]:
                raise ValueError("Framework trace contains no complete supported spans.")
            origin = min(item["started"] for item in state["spans"])
            end = max(item["ended"] for item in state["spans"])
            known = {item["raw_id"] for item in state["spans"]}
            spans = []
            for item in state["spans"]:
                start_ms = int((item["started"] - origin).total_seconds() * 1000)
                end_ms = int((item["ended"] - origin).total_seconds() * 1000 + 0.999999)
                usage = item["usage"]
                spans.append({
                    "span_id": hashlib.sha256(item["raw_id"].encode()).hexdigest()[:32],
                    "parent_id": (hashlib.sha256(item["raw_parent"].encode()).hexdigest()[:32]
                                  if item["raw_parent"] in known else None),
                    "name": item["name"], "kind": item["kind"],
                    "status": item["status"], "start_offset_ms": start_ms,
                    "duration_ms": max(0, end_ms - start_ms),
                    "input_tokens": usage[0] if usage else None,
                    "output_tokens": usage[1] if usage else None,
                })
            duration_ms = max(0, int((end - origin).total_seconds() * 1000 + 0.999999))
            body = ExternalTraceCreate.model_validate({
                "schema_version": 1, "source": self.source,
                "idempotency_key": idempotency_key or "trace-" + hashlib.sha256(
                    selected.encode()).hexdigest()[:32],
                "started_at": origin, "duration_ms": duration_ms,
                "reported_status": reported_status, "spans": spans, "output": output,
            })
            state["finished"] = True
            return body.model_dump(mode="json")
