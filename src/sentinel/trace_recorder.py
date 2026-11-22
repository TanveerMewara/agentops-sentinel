"""Opt-in instrumentation for synchronous Python agents; never executes a tool."""
from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from .external_traces import ExternalTraceCreate


class TraceRecorder:
    """Use one recorder per run and thread. Capture names/timings, not prompts."""

    def __init__(self, source="python_agent"):
        self.source = source
        self.started_at = datetime.now(timezone.utc)
        self._start = monotonic()
        self._spans = []
        self._stack = []
        self._finished = False

    def _offset(self):
        return int((monotonic() - self._start) * 1000)

    @contextmanager
    def span(self, name, kind="agent"):
        if self._finished:
            raise ValueError("This trace is already finalized.")
        item = {"span_id": uuid4().hex,
            "parent_id": self._stack[-1]["span_id"] if self._stack else None,
            "name": name, "kind": kind, "status": "completed",
            "start_offset_ms": self._offset(), "duration_ms": 0,
            "input_tokens": None, "output_tokens": None}
        self._stack.append(item)
        try:
            yield item
        except BaseException:
            item["status"] = "failed"
            raise
        finally:
            item["duration_ms"] = self._offset() - item["start_offset_ms"]
            self._stack.pop()
            self._spans.append(item)

    def finish(self, output, *, reported_status="succeeded", idempotency_key=None):
        if self._finished or self._stack:
            raise ValueError("Finalize once, after all spans have closed.")
        body = ExternalTraceCreate.model_validate({
            "schema_version": 1, "source": self.source,
            "idempotency_key": idempotency_key or "trace-" + uuid4().hex,
            "started_at": self.started_at, "duration_ms": self._offset(),
            "reported_status": reported_status, "spans": self._spans, "output": output})
        self._finished = True
        # Keep this returned payload and key for uncertain-write replay.
        return body.model_dump(mode="json")
