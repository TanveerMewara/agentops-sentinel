import time
import unittest
from contextlib import contextmanager
from threading import Event
from urllib.error import HTTPError, URLError

from sentinel.security import Principal
from sentinel.service import maintain_lease
from sentinel.worker import Worker


class FakeResult:
    def fetchone(self):
        return {"operation_id": "operation-1"}


class FakeConnection:
    def __init__(self, calls, renewed):
        self.calls = calls
        self.renewed = renewed

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        self.renewed.set()
        return FakeResult()


class FakeDatabase:
    def __init__(self):
        self.calls = []
        self.renewed = Event()

    @contextmanager
    def connect(self):
        yield FakeConnection(self.calls, self.renewed)


class FlakyWorker(Worker):
    def __init__(self, stop_event, delays):
        super().__init__(
            "https://sentinel.test", "snt_test_secret",
            sleeper=delays.append, random_source=lambda: 0.5,
        )
        self.stop_event = stop_event
        self.attempts = 0

    def run_once(self):
        self.attempts += 1
        if self.attempts <= 2:
            raise URLError("temporary outage")
        self.stop_event.set()
        return 0


class LeaseHeartbeatTests(unittest.TestCase):
    def test_heartbeat_renews_and_stops_with_context(self):
        database = FakeDatabase()
        principal = Principal("key-1", "org-1", "worker")
        operation = {
            "operation_id": "operation-1",
            "current_attempt_id": "attempt-1",
        }

        with maintain_lease(
            database, principal, operation, "executing", 30,
            heartbeat_seconds=0.01,
        ):
            self.assertTrue(database.renewed.wait(timeout=2))

        self.assertGreaterEqual(len(database.calls), 1)
        calls_after_exit = len(database.calls)
        time.sleep(0.03)
        self.assertEqual(len(database.calls), calls_after_exit)
        _, parameters = database.calls[0]
        self.assertEqual(parameters, (30, "operation-1", "org-1", "executing", "attempt-1"))


class WorkerRetryTests(unittest.TestCase):
    def test_waiting_workflow_does_not_block_other_queued_runs(self):
        class QueueWorker(Worker):
            def __init__(self):
                super().__init__("https://sentinel.test", "test")
                self.approved = False
                self.finished = False

            def request(self, path, payload=None):
                if path.startswith("/v1/workflows/actionable"):
                    return [{"run_id": "waiting"}] + ([] if self.finished else [{"run_id": "ready"}])
                if path.endswith("/workflow/start"):
                    return {"status": "waiting_approval"}
                if path == "/v1/runs/waiting/workflow/resume":
                    if not self.approved:
                        raise HTTPError(path, 409, "Approval required", {}, None)
                    return {"status": "completed"}
                if path == "/v1/runs/ready/workflow/resume":
                    self.finished = True
                    return {"status": "completed"}
                return []

        worker = QueueWorker()
        self.assertEqual(worker.run_once(), 1)
        self.assertTrue(worker.finished)
        worker.approved = True
        self.assertEqual(worker.run_once(), 1)

    def test_transient_failures_back_off_and_then_recover(self):
        stop_event = Event()
        delays = []
        worker = FlakyWorker(stop_event, delays)

        worker.run_forever(
            interval_seconds=1,
            max_backoff_seconds=10,
            stop_event=stop_event,
        )

        self.assertEqual(worker.attempts, 3)
        self.assertEqual(delays, [1.0, 2.0])

    def test_authentication_failure_is_not_retried(self):
        error = HTTPError("http://sentinel.test", 401, "Unauthorized", {}, None)
        self.assertFalse(Worker.is_transient(error))
        self.assertTrue(Worker.is_transient(HTTPError(
            "http://sentinel.test", 503, "Unavailable", {}, None
        )))


if __name__ == "__main__":
    unittest.main()
