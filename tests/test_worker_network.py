"""Worker credentials must never follow an API redirect."""
import unittest
from urllib.error import HTTPError

from sentinel.worker import Worker
from test_client_network import QuietHandler, serving


class WorkerNetworkTests(unittest.TestCase):
    def test_redirects_do_not_forward_credentials_or_repeat_writes(self):
        source_calls, target_calls = [], []

        class Target(QuietHandler):
            def do_GET(self):
                target_calls.append(self.headers.get("X-API-Key"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            do_POST = do_GET

        with serving(Target) as target_port:
            class Source(QuietHandler):
                def do_GET(self):
                    source_calls.append(self.command)
                    self.send_response(int(self.path.rsplit("/", 1)[-1]))
                    self.send_header("Location", f"http://127.0.0.1:{target_port}/v1/trap")
                    self.end_headers()
                do_POST = do_GET

            with serving(Source) as port:
                worker = Worker(f"http://127.0.0.1:{port}", "snt_synthetic_secret")
                for code in (301, 302, 303, 307, 308):
                    for body in (None, {"operation_id": "stable"}):
                        with self.assertRaises(HTTPError) as caught:
                            worker.request(f"/v1/redirect/{code}", body)
                        self.assertEqual(caught.exception.code, code)
                        caught.exception.close()
        self.assertEqual(target_calls, [])
        self.assertEqual(len(source_calls), 10)

    def test_insecure_external_urls_and_non_api_paths_are_rejected(self):
        for url in ("http://sentinel.test", "https://user:secret@sentinel.test", "https://sentinel.test?token=secret"):
            with self.assertRaises(ValueError):
                Worker(url, "snt_synthetic_secret")
        worker = Worker("https://sentinel.test", "snt_synthetic_secret")
        with self.assertRaises(ValueError):
            worker.request("//attacker.test/v1/me")
