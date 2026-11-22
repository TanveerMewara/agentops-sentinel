"""Real HTTP reconciliation checks; Docker is not required."""
import importlib
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from uuid import uuid4

lesson = importlib.import_module("lessons.05_reconcile_booking")
Action, BookingAdapter, execute_once, State = lesson.Action, lesson.BookingAdapter, lesson.execute_once, lesson.State
ROOT = Path(__file__).resolve().parents[1]


class ReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "lessons.reconciliation_service:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            cwd=ROOT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cls.addClassCleanup(cls.stop_server)
        for _ in range(80):
            if cls.server.poll() is not None:
                raise RuntimeError("Lesson server exited during startup")
            try:
                BookingAdapter(cls.base).request("/health", timeout=0.3)
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("Lesson server did not become ready")

    @classmethod
    def stop_server(cls):
        if cls.server.poll() is None:
            cls.server.kill()
        cls.server.wait(timeout=10)

    def action(self):
        label = uuid4().hex
        return Action(label, f"customer-{label}", "2030-01-15 10:00")

    def assert_one_booking(self, action, adapter):
        bookings = adapter.request("/bookings")
        self.assertEqual(sum(b["customer"] == action.customer for b in bookings), 1)
        self.assertEqual(adapter.submissions, 1)

    def test_delayed_reply_resolves_with_read_only_lookup(self):
        action, adapter = self.action(), BookingAdapter(self.base)
        result = execute_once(action, adapter)
        self.assertEqual(result.state, State.SUCCEEDED)
        self.assertTrue(any("--timeout--> unknown" in step for step in result.history))
        self.assertEqual(result.booking_id, adapter.lookup(action)["booking_id"])
        self.assertEqual(adapter.lookups, 2)  # One reconciliation and our verification.
        self.assert_one_booking(action, adapter)

    def test_immediate_success_does_not_need_lookup(self):
        action, adapter = self.action(), BookingAdapter(self.base)
        result = execute_once(action, adapter, delay=0)
        self.assertEqual(result.state, State.SUCCEEDED)
        self.assertEqual(adapter.lookups, 0)
        self.assert_one_booking(action, adapter)

    def test_missing_lookup_capability_routes_to_review(self):
        action, adapter = self.action(), BookingAdapter(self.base, supports_lookup=False)
        result = execute_once(action, adapter)
        self.assertEqual(result.state, State.NEEDS_REVIEW)
        self.assertIsNone(result.booking_id)
        self.assertEqual(adapter.lookups, 0)
        self.assert_one_booking(action, adapter)

    def test_mismatched_receipt_cannot_confirm_success(self):
        class MismatchedAdapter(BookingAdapter):
            def lookup(self, action):
                receipt = super().lookup(action)
                return {**receipt, "operation_id": "different-operation"}
        action, adapter = self.action(), MismatchedAdapter(self.base)
        result = execute_once(action, adapter)
        self.assertEqual(result.state, State.NEEDS_REVIEW)
        self.assert_one_booking(action, adapter)

    def test_not_found_does_not_authorize_retry(self):
        class MissingResultAdapter(BookingAdapter):
            def lookup(self, action):
                self.lookups += 1
                return self.request("/operations/absent-" + uuid4().hex)
        action, adapter = self.action(), MissingResultAdapter(self.base)
        result = execute_once(action, adapter)
        self.assertEqual(result.state, State.NEEDS_REVIEW)
        self.assert_one_booking(action, adapter)

    def test_unreadable_submit_reply_can_be_reconciled(self):
        class BrokenReplyAdapter(BookingAdapter):
            def submit(self, action, delay):
                super().submit(action, 0)
                # Simulate unusable response content after the actual HTTP operation.
                return {"unexpected": "response"}
        action, adapter = self.action(), BrokenReplyAdapter(self.base)
        result = execute_once(action, adapter)
        self.assertEqual(result.state, State.SUCCEEDED)
        self.assertTrue(any("--outcome_uncertain--> unknown" in step for step in result.history))
        self.assert_one_booking(action, adapter)

    def test_receipt_must_match_all_action_details(self):
        action = self.action()
        valid = {"operation_id": action.operation_id, "customer": action.customer,
                 "slot": action.slot, "booking_id": "booking-1"}
        for field in ("operation_id", "customer", "slot", "booking_id"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                BookingAdapter.confirmed_booking(action, {**valid, field: ""})


if __name__ == "__main__":
    unittest.main()
