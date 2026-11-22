"""Provider faults over real sockets, with fictional data and no external services."""
import json
import socket
import unittest

from sentinel.booking_adapter import BookingAdapter, EvidenceMismatch, UncertainOutcome
from test_client_network import QuietHandler, serving

ACTION = {"customer": "Fictional lab buyer", "slot": "2030-01-01T10:00:00Z"}


class BookingFailureLabTests(unittest.TestCase):
    def scenario(self, fault):
        receipts, writes, reads = {}, [], []

        class Provider(QuietHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                operation = payload["operation_id"]
                writes.append(operation)
                receipts[operation] = {"operation_id": operation, **ACTION, "booking_id": "lab-receipt"}
                # The write committed, then the TCP reply disappeared.
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)

            def do_GET(self):
                reads.append(self.path)
                if fault == "unavailable" or (fault == "temporary" and len(reads) < 3):
                    self.send_response(503)
                    self.end_headers()
                    return
                if fault == "missing":
                    self.send_response(404)
                    self.end_headers()
                    return
                receipt = dict(receipts["lab-operation"])
                if fault == "mismatch":
                    receipt["customer"] = "Different fictional buyer"
                data = json.dumps(receipt).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        delays = []
        with serving(Provider) as port:
            adapter = BookingAdapter(f"http://127.0.0.1:{port}", sleeper=delays.append)
            with self.assertRaises(UncertainOutcome):
                adapter.execute("lab-operation", ACTION)
            # Recreate the client: the receipt lives at the provider, not in its memory.
            adapter = BookingAdapter(f"http://127.0.0.1:{port}", sleeper=delays.append)
            if fault in ("healthy", "temporary"):
                self.assertEqual(adapter.reconcile("lab-operation", ACTION), "lab-receipt")
            else:
                expected = EvidenceMismatch if fault == "mismatch" else UncertainOutcome
                with self.assertRaises(expected):
                    adapter.reconcile("lab-operation", ACTION)
        self.assertEqual(writes, ["lab-operation"])
        self.assertEqual(len(receipts), 1)
        expected_reads = 3 if fault in ("temporary", "unavailable") else 1
        self.assertEqual(reads, ["/operations/lab-operation"] * expected_reads)
        self.assertEqual(delays, [0.1, 0.2] if expected_reads == 3 else [])

    def test_committed_write_lost_reply_and_recreated_client(self):
        self.scenario("healthy")

    def test_temporary_provider_outage_recovers_without_another_write(self):
        self.scenario("temporary")

    def test_provider_outage_exhausts_reads_without_another_write(self):
        self.scenario("unavailable")

    def test_missing_receipt_never_authorizes_another_write(self):
        self.scenario("missing")

    def test_contradictory_receipt_never_authorizes_another_write(self):
        self.scenario("mismatch")
