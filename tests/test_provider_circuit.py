import json
from threading import Event, Thread
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from urllib.error import HTTPError

from fastapi import HTTPException
from sentinel.adapters import AdapterRegistry
from sentinel.booking_adapter import BookingAdapter, UncertainOutcome
from sentinel.provider_circuit import CircuitOpen, ProviderCircuit
from sentinel.service import execute
from sentinel.runs import claim_tool_call
from test_booking_recovery import ACTION, Result, Opener


class Health(Result):
    def read(self, *args):
        return json.dumps({"status": "ok"}).encode()


class ProviderCircuitTests(unittest.TestCase):
    def circuit(self):
        now = [0]
        circuit = ProviderCircuit(failure_threshold=2, cooldown_seconds=10, clock=lambda: now[0])
        return circuit, now

    def test_open_circuit_blocks_writes_until_a_read_only_probe(self):
        circuit, now = self.circuit()
        circuit.record_failure()
        circuit.before_write(lambda: self.fail("Healthy circuit must not probe"))
        circuit.record_failure()
        with self.assertRaises(CircuitOpen):
            circuit.before_write(lambda: self.fail("Cooldown must not probe"))
        now[0] = 10
        probes = []
        circuit.before_write(lambda: probes.append("GET health"))
        circuit.before_write(lambda: self.fail("Closed circuit must not probe"))
        self.assertEqual(probes, ["GET health"])

    def test_failed_probe_restarts_cooldown_without_exposing_its_error(self):
        circuit, now = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        now[0] = 10
        def fail():
            raise RuntimeError("PRIVATE credential")
        with self.assertRaises(CircuitOpen) as caught:
            circuit.before_write(fail)
        self.assertNotIn("PRIVATE", str(caught.exception))
        now[0] = 19
        with self.assertRaises(CircuitOpen):
            circuit.before_write(lambda: self.fail("New cooldown must hold"))

    def test_only_one_probe_runs_and_concurrent_writes_are_blocked(self):
        circuit, now = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        now[0] = 10
        entered, release = Event(), Event()
        errors = []
        def probe():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Probe release timed out")
        def run():
            try:
                circuit.before_write(probe)
            except Exception as error:
                errors.append(error)
        thread = Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(CircuitOpen):
                circuit.before_write(lambda: self.fail("Second probe must not run"))
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_dispatch_is_blocked_before_ledger_claim(self):
        circuit, _ = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        adapter = BookingAdapter("http://127.0.0.1:8002", circuit=circuit)
        with patch("sentinel.service.claim_for_execution") as claim:
            with self.assertRaises(HTTPException) as caught:
                execute(None, None, "operation", adapter)
        claim.assert_not_called()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.headers["Retry-After"], "10")
        registry = AdapterRegistry(adapter)
        contract = {"name": "book_viewing", "version": "1.0.0", "risk_level": "high", "approval_mode": "always"}
        with self.assertRaises(HTTPException):
            registry.prepare_execution(contract)

    def test_registered_claim_blocks_before_approval_or_lease_sql(self):
        circuit, _ = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        registry = AdapterRegistry(BookingAdapter("http://127.0.0.1:8002", circuit=circuit))
        contract = {"name": "book_viewing", "version": "1.0.0", "risk_level": "high", "approval_mode": "always"}
        database = MagicMock()
        connection = database.connect.return_value.__enter__.return_value
        with patch("sentinel.runs._locked_tool_call", return_value=({}, contract)), \
                patch("sentinel.runs.get_run", return_value={"status": "running"}):
            with self.assertRaises(HTTPException) as caught:
                claim_tool_call(database, SimpleNamespace(organization_id="org"), "run", "call", 30, registry)
        self.assertEqual(caught.exception.status_code, 503)
        connection.execute.assert_not_called()

    def test_matching_recovery_closes_circuit_without_a_write(self):
        circuit, _ = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        adapter = BookingAdapter("http://127.0.0.1:8002", circuit=circuit)
        adapter.opener = Opener([Result()])
        self.assertEqual(adapter.reconcile("operation", ACTION), "receipt")
        adapter.prepare_execution()
        self.assertEqual(adapter.opener.methods, ["GET"])

    def test_health_probe_is_get_and_never_replays_the_failed_write(self):
        circuit, now = self.circuit()
        adapter = BookingAdapter("http://127.0.0.1:8002", circuit=circuit)
        adapter.opener = Opener([TimeoutError(), TimeoutError(), Health()])
        for _ in range(2):
            with self.assertRaises(UncertainOutcome):
                adapter.execute("operation", ACTION)
        with self.assertRaises(UncertainOutcome):
            adapter.execute("operation", ACTION)
        self.assertEqual(adapter.opener.methods, ["POST", "POST"])
        now[0] = 10
        adapter.prepare_execution()
        self.assertEqual(adapter.opener.methods, ["POST", "POST", "GET"])

    def test_permanent_http_error_does_not_trip_the_outage_circuit(self):
        circuit, _ = self.circuit()
        adapter = BookingAdapter("http://127.0.0.1:8002", circuit=circuit)
        adapter.opener = Opener([HTTPError("private", 404, "private", {}, None)] * 3)
        for _ in range(3):
            with self.assertRaises(UncertainOutcome):
                adapter.reconcile("operation", ACTION)
        adapter.prepare_execution()
        self.assertEqual(adapter.opener.methods, ["GET"] * 3)

    def test_invalid_limits_are_rejected(self):
        for threshold in (True, 0, 101):
            with self.assertRaises(ValueError):
                ProviderCircuit(failure_threshold=threshold)
        for cooldown in (True, 0, 3601, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ProviderCircuit(cooldown_seconds=cooldown)

    def test_real_provider_outage_blocks_dispatch_and_recovers_via_health_get(self):
        from test_client_network import QuietHandler, serving
        posts, gets = [], []
        circuit, now = self.circuit()

        class Provider(QuietHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                posts.append(payload["operation_id"])
                if len(posts) <= 2:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.reply({"operation_id": payload["operation_id"], **ACTION, "booking_id": "receipt"})

            def do_GET(self):
                gets.append(self.path)
                self.reply({"status": "ok"})

            def reply(self, payload):
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        with serving(Provider) as port:
            adapter = BookingAdapter(f"http://127.0.0.1:{port}", circuit=circuit)
            for operation in ("failed-1", "failed-2"):
                with self.assertRaises(UncertainOutcome):
                    adapter.execute(operation, ACTION)
            with self.assertRaises(HTTPException):
                adapter.prepare_execution()
            self.assertEqual(posts, ["failed-1", "failed-2"])
            self.assertEqual(gets, [])
            now[0] = 10
            adapter.prepare_execution()
            self.assertEqual(adapter.execute("operation", ACTION), "receipt")
        self.assertEqual(posts, ["failed-1", "failed-2", "operation"])
        self.assertEqual(gets, ["/health"])

    def test_invalid_health_response_does_not_reopen_dispatch(self):
        circuit, now = self.circuit()
        circuit.record_failure()
        circuit.record_failure()
        now[0] = 10
        adapter = BookingAdapter("http://127.0.0.1:8002", circuit=circuit)
        adapter.opener = Opener([Result()])
        with self.assertRaises(HTTPException):
            adapter.prepare_execution()
        with self.assertRaises(UncertainOutcome):
            adapter.execute("operation", ACTION)
        self.assertEqual(adapter.opener.methods, ["GET"])
