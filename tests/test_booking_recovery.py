"""Read-only recovery retries cannot repeat the booking write."""
import unittest
from urllib.error import HTTPError, URLError

from sentinel.booking_adapter import BookingAdapter, EvidenceMismatch, UncertainOutcome

ACTION = {"customer": "Fictional buyer", "slot": "2030-01-01T10:00:00Z"}
RECEIPT = {"operation_id": "operation", **ACTION, "booking_id": "receipt"}


class Result:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, *args):
        import json
        return json.dumps(RECEIPT).encode()


class Opener:
    def __init__(self, results):
        self.results, self.methods = iter(results), []
    def open(self, request, **kwargs):
        self.methods.append(request.get_method())
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


class BookingRecoveryTests(unittest.TestCase):
    def test_real_redirect_does_not_forward_a_write_or_retry_a_lookup(self):
        from test_client_network import QuietHandler, serving
        targets, sources = [], []
        class Target(QuietHandler):
            def do_GET(self):
                targets.append(self.command)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            do_POST = do_GET
        with serving(Target) as target_port:
            class Source(QuietHandler):
                def do_GET(self):
                    sources.append(self.command)
                    self.send_response(307)
                    self.send_header("Location", f"http://127.0.0.1:{target_port}/trap")
                    self.end_headers()
                do_POST = do_GET
            with serving(Source) as source_port:
                adapter = BookingAdapter(f"http://127.0.0.1:{source_port}")
                with self.assertRaises(UncertainOutcome):
                    adapter.execute("operation", ACTION)
                with self.assertRaises(UncertainOutcome):
                    adapter.reconcile("operation", ACTION)
        self.assertEqual(sources, ["POST", "GET"])
        self.assertEqual(targets, [])

    def adapter(self, results):
        delays = []
        adapter = BookingAdapter("http://127.0.0.1:8002", sleeper=delays.append)
        adapter.opener = Opener(results)
        return adapter, delays

    def test_lost_write_response_is_not_retried_but_evidence_reads_are(self):
        adapter, delays = self.adapter([TimeoutError("PRIVATE"), URLError("PRIVATE"), TimeoutError(), Result()])
        with self.assertRaises(UncertainOutcome) as caught:
            adapter.execute("operation", ACTION)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual(adapter.reconcile("operation", ACTION), "receipt")
        self.assertEqual(adapter.opener.methods, ["POST", "GET", "GET", "GET"])
        self.assertEqual(delays, [0.1, 0.2])

    def test_exhaustion_is_bounded_and_remains_uncertain(self):
        adapter, delays = self.adapter([TimeoutError()] * 3)
        with self.assertRaises(UncertainOutcome):
            adapter.reconcile("operation", ACTION)
        self.assertEqual(adapter.opener.methods, ["GET"] * 3)
        self.assertEqual(len(delays), 2)

    def test_not_found_redirects_and_bad_json_are_not_retried(self):
        for error in (HTTPError("private", 404, "PRIVATE", {}, None),
                      HTTPError("private", 307, "PRIVATE", {}, None), ValueError("PRIVATE")):
            adapter, delays = self.adapter([error])
            with self.assertRaises(UncertainOutcome):
                adapter.reconcile("operation", ACTION)
            self.assertEqual(adapter.opener.methods, ["GET"])
            self.assertEqual(delays, [])

    def test_mismatched_evidence_stops_without_another_lookup(self):
        adapter, delays = self.adapter([Result()])
        with self.assertRaises(EvidenceMismatch):
            adapter.reconcile("other-operation", ACTION)
        self.assertEqual(adapter.opener.methods, ["GET"])
        self.assertEqual(delays, [])

    def test_policy_rejects_unbounded_attempts_and_insecure_provider_urls(self):
        for attempts in (True, 0, 4):
            with self.assertRaises(ValueError):
                BookingAdapter("http://127.0.0.1:8002", recovery_attempts=attempts)
        with self.assertRaises(ValueError):
            BookingAdapter("http://provider.example.test")
