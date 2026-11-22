"""Observability must not reopen dispatch or disclose shared failure history."""
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException
from sentinel.adapters import AdapterRegistry
from sentinel.booking_adapter import BookingAdapter
from sentinel.operations_overview import operations_overview
from sentinel.provider_circuit import ProviderCircuit


class CircuitSnapshotTests(unittest.TestCase):
    def test_snapshot_does_not_reopen_an_expired_cooldown_or_disclose_counts(self):
        now = [0]
        circuit = ProviderCircuit(failure_threshold=2, cooldown_seconds=10, clock=lambda: now[0])
        expected = {"state": "closed", "retry_after_seconds": 0, "scope": "api_process"}
        self.assertEqual(circuit.snapshot(), expected)
        circuit.record_failure()
        circuit.record_failure()
        now[0] = 0.1
        self.assertEqual(circuit.snapshot(), {**expected, "state": "open", "retry_after_seconds": 10})
        now[0] = 100
        for _ in range(3):
            self.assertEqual(circuit.snapshot(), {**expected, "state": "open"})
        probes = []
        circuit.before_write(lambda: probes.append("GET health"))
        self.assertEqual(probes, ["GET health"])
        self.assertEqual(circuit.snapshot(), expected)

    def test_snapshot_remains_readable_during_a_probe(self):
        now = [0]
        circuit = ProviderCircuit(failure_threshold=1, cooldown_seconds=1, clock=lambda: now[0])
        circuit.record_failure()
        now[0] = 1
        entered, release = Event(), Event()
        errors = []
        def probe():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Timed out waiting for probe release")
        def run():
            try:
                circuit.before_write(probe)
            except Exception as error:
                errors.append(error)
        thread = Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(circuit.snapshot(), {"state": "probing", "retry_after_seconds": 0, "scope": "api_process"})
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_absent_reference_adapter_does_not_invent_provider_health(self):
        self.assertIsNone(AdapterRegistry().booking_circuit_snapshot())
        adapter = BookingAdapter("http://127.0.0.1:8002")
        adapter.opener = MagicMock()
        snapshot = AdapterRegistry(adapter).booking_circuit_snapshot()
        self.assertEqual(set(snapshot), {"state", "retry_after_seconds", "scope"})
        adapter.opener.open.assert_not_called()

    def test_worker_cannot_read_operational_signals(self):
        database = MagicMock()
        with self.assertRaises(HTTPException) as caught:
            operations_overview(database, SimpleNamespace(role="worker"), None, None)
        self.assertEqual(caught.exception.status_code, 403)
        database.connect.assert_not_called()
