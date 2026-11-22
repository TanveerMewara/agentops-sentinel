"""Real loopback sockets and TLS; no paid service or external credentials."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sentinel.client import NoRedirect, SentinelClient, SentinelError


@contextmanager
def serving(handler, tls=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if tls:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ClientNetworkTests(unittest.TestCase):
    def test_redirects_never_forward_credentials_or_repeat_writes(self):
        target_calls, source_calls = [], []

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
                client = SentinelClient(f"http://127.0.0.1:{port}", "snt_synthetic_secret")
                for code in (301, 302, 303, 307, 308):
                    for body in (None, {"private": "synthetic"}):
                        with self.assertRaises(SentinelError) as caught:
                            client.request(f"/v1/redirect/{code}", body)
                        self.assertEqual(caught.exception.status, code)
        self.assertEqual(target_calls, [])
        self.assertEqual(len(source_calls), 10)

    def test_tls_verification_and_authenticated_json_exchange(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
        received = []

        class Handler(QuietHandler):
            def do_POST(self):
                received.append((self.headers.get("X-API-Key"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        with TemporaryDirectory(prefix="sentinel-tls-") as directory:
            cert_path, key_path = Path(directory) / "certificate.pem", Path(directory) / "key.pem"
            cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            with serving(Handler, context) as port:
                client = SentinelClient(f"https://localhost:{port}", "snt_synthetic_secret")
                with self.assertRaises(SentinelError) as caught:
                    client.request("/v1/probe", {"idempotency_key": "stable"})
                self.assertEqual(caught.exception.status, 0)
                self.assertEqual(received, [])
                trusted = ssl.create_default_context(cafile=str(cert_path))
                client.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=trusted))
                self.assertEqual(client.request("/v1/probe", {"idempotency_key": "stable"}), {"status": "ok"})
        self.assertEqual(received, [("snt_synthetic_secret", {"idempotency_key": "stable"})])
