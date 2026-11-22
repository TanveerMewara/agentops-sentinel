"""Small API-driven worker. A durable queue/notification layer comes later."""
import json
import os
import random
import time
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from sentinel.client import NoRedirect, validate_api_url


class Worker:
    def __init__(self, api_url: str, api_key: str, *, sleeper=time.sleep,
                 random_source=random.random):
        self.api_url = validate_api_url(api_url)
        self.api_key = api_key
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.sleeper = sleeper
        self.random_source = random_source

    def request(self, path: str, payload: dict | None = None):
        if not path.startswith("/v1/"):
            raise ValueError("Worker requests must use a Sentinel /v1/ endpoint.")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.api_url + path,
            data=data,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with self.opener.open(request, timeout=15) as response:
            return json.load(response)

    def run_once(self) -> int:
        completed = 0
        workflows = self.request("/v1/workflows/actionable?limit=25")
        for run in workflows:
            try:
                self.request(f"/v1/runs/{run['run_id']}/workflow/start", {})
                result = self.request(f"/v1/runs/{run['run_id']}/workflow/resume", {})
            except HTTPError as error:
                if error.code in (409, 422):
                    continue
                raise
            if result["status"] == "completed":
                completed += 1
        for status in ("executing", "unknown"):
            calls = self.request(f"/v1/tool-calls?status={status}&limit=25")
            for call in calls:
                try:
                    result = self.request(
                        f"/v1/runs/{call['run_id']}/tool-calls/"
                        f"{call['tool_call_id']}/reconcile", {}
                    )
                except HTTPError as error:
                    if error.code == 409:
                        continue
                    raise
                print(
                    f"tool call {call['tool_call_id']}: recovered as {result['status']}",
                    flush=True,
                )
                completed += 1

        calls = self.request("/v1/tool-calls?status=authorized&limit=25")
        for call in calls:
            try:
                result = self.request(
                    f"/v1/runs/{call['run_id']}/tool-calls/"
                    f"{call['tool_call_id']}/execute", {}
                )
            except HTTPError as error:
                if error.code in (409, 501):
                    continue
                raise
            print(f"tool call {call['tool_call_id']}: {result['status']}", flush=True)
            completed += 1

        # Recovery never repeats the external write. It only asks an adapter for
        # evidence about operations with an uncertain or abandoned outcome.
        for status in ("executing", "unknown"):
            operations = self.request(f"/v1/operations?status={status}&limit=25")
            for operation in operations:
                try:
                    result = self.request(
                        f"/v1/operations/{operation['operation_id']}/reconcile", {}
                    )
                except HTTPError as error:
                    # An active lease or another recovery worker owns the record.
                    if error.code == 409:
                        continue
                    raise
                print(f"{operation['operation_id']}: recovered as {result['status']}", flush=True)
                completed += 1

        operations = self.request("/v1/operations?status=authorized&limit=25")
        for operation in operations:
            try:
                result = self.request(
                    f"/v1/operations/{operation['operation_id']}/execute", {}
                )
            except HTTPError as error:
                # Another worker may have claimed it after our list request.
                if error.code == 409:
                    continue
                raise
            print(f"{operation['operation_id']}: {result['status']}", flush=True)
            completed += 1
        return completed

    @staticmethod
    def is_transient(error: Exception) -> bool:
        if isinstance(error, HTTPError):
            return error.code in (408, 425, 429) or error.code >= 500
        return isinstance(error, (URLError, TimeoutError, OSError))

    def run_forever(self, interval_seconds: float = 1.0,
                    max_backoff_seconds: float = 30.0,
                    stop_event: Event | None = None):
        if interval_seconds <= 0 or max_backoff_seconds <= 0:
            raise ValueError("Worker polling and backoff intervals must be positive.")
        stop_event = stop_event or Event()
        failures = 0
        while not stop_event.is_set():
            try:
                self.run_once()
                failures = 0
                delay = interval_seconds
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                if not self.is_transient(error):
                    raise
                failures += 1
                exponent = min(failures - 1, 20)
                base = min(max_backoff_seconds, interval_seconds * (2 ** exponent))
                delay = base * (0.8 + 0.4 * self.random_source())
                print(
                    f"Worker request failed ({type(error).__name__}); retrying in {delay:.1f}s.",
                    flush=True,
                )
            if not stop_event.is_set():
                self.sleeper(delay)


def from_environment() -> Worker:
    api_url = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000")
    api_key = os.environ.get("SENTINEL_WORKER_API_KEY")
    if not api_key:
        raise RuntimeError("SENTINEL_WORKER_API_KEY is required.")
    return Worker(api_url, api_key)


if __name__ == "__main__":
    try:
        from_environment().run_forever()
    except (HTTPError, URLError) as error:
        raise SystemExit(f"Worker cannot reach Sentinel: {type(error).__name__}") from error
