from datetime import datetime, timedelta, timezone
import io
import json
import unittest
from urllib.error import HTTPError, URLError

from pydantic import ValidationError
from sentinel.access import KeyCreate
from sentinel.client import NoRedirect, SentinelClient, SentinelError


class ClientAccessTests(unittest.TestCase):
    def test_expiry_rejects_past_and_naive_dates(self):
        for value in (datetime.now(timezone.utc) - timedelta(minutes=1), datetime.now() + timedelta(days=1)):
            with self.assertRaises(ValidationError):
                KeyCreate(label="fixture", role="worker", expires_at=value)
        self.assertIsNotNone(KeyCreate(label="fixture", role="worker", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)).expires_at)

    def test_client_rejects_cleartext_remote_and_credential_urls(self):
        for url in ("http://example.test", "https://user:password@example.test", "https://example.test?token=secret", "ftp://localhost"):
            with self.assertRaises(ValueError):
                SentinelClient(url, "snt_fixture_secret")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, None, None, "https://other.test"))

    def test_write_timeout_is_not_retried_and_errors_do_not_echo_secrets(self):
        class FailingOpener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise URLError("snt_private_key customer-private")
        client = SentinelClient("http://localhost", "snt_private_key")
        client.opener = FailingOpener()
        with self.assertRaises(SentinelError) as caught:
            client.create_run("version", "stable-key", {})
        self.assertEqual(client.opener.calls, 1)
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(caught.exception.status, 0)

    def test_client_keeps_idempotency_key_and_http_status(self):
        class Opener:
            def open(self, request, timeout):
                self.payload = json.loads(request.data)
                return io.BytesIO(b'{"run_id":"fixture"}')
        client = SentinelClient("http://localhost", "snt_fixture_secret")
        client.opener = Opener()
        client.create_run("version", "stable-request-key", {"classification": "standard"})
        self.assertEqual(client.opener.payload["idempotency_key"], "stable-request-key")
        class Forbidden:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 403, "private", {}, io.BytesIO(b'private'))
        client.opener = Forbidden()
        with self.assertRaises(SentinelError) as caught:
            client.identity()
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn("private", str(caught.exception))

    def test_otlp_client_uses_managed_import_path_and_explicit_metadata(self):
        class Opener:
            def open(self, request, timeout):
                self.path = request.full_url
                self.payload = json.loads(request.data)
                return io.BytesIO(b'{"trace_id":"fixture"}')
        client = SentinelClient("http://localhost", "snt_fixture_secret")
        client.opener = Opener()
        client.submit_otlp_trace("run-1", {"resourceSpans": []}, {"answer": "safe"},
            "stable-otlp-key", trace_id="a"*32, source="otel_agent",
            reported_status="needs_review")
        self.assertTrue(client.opener.path.endswith('/v1/runs/run-1/external-trace/otlp'))
        self.assertEqual(client.opener.payload, {"schema_version": 1,
            "idempotency_key": "stable-otlp-key", "trace_id": "a"*32,
            "source": "otel_agent", "reported_status": "needs_review",
            "output": {"answer": "safe"}, "otlp": {"resourceSpans": []}})
        client.finalize_otlp_trace("run-1", {"answer": "safe"},
            "stable-finalize-key", reported_status="succeeded")
        self.assertTrue(client.opener.path.endswith(
            '/v1/runs/run-1/external-trace/otlp/finalize'))
        self.assertEqual(client.opener.payload, {"idempotency_key": "stable-finalize-key",
            "reported_status": "succeeded", "output": {"answer": "safe"}})

    def test_telemetry_client_exposes_policy_rate_summary_and_lifecycle_calls(self):
        class Opener:
            calls=[]
            def open(self, request, timeout):
                self.calls.append((request.get_method(),request.full_url,
                    json.loads(request.data) if request.data else None))
                return io.BytesIO(b'{}')
        client=SentinelClient("http://localhost","snt_fixture_secret")
        client.opener=Opener()
        client.telemetry("run-1"); client.telemetry_policy()
        client.set_telemetry_policy(30,["traces","metrics"],require_token_usage=True)
        client.add_rate_card("model.standard","1.0","2.0"); client.rate_cards()
        client.purge_expired_telemetry(); client.delete_run_telemetry("run-1")
        self.assertEqual([call[0] for call in client.opener.calls],
                         ["GET","GET","PUT","POST","GET","POST","DELETE"])
        self.assertTrue(client.opener.calls[-1][1].endswith('/v1/runs/run-1/telemetry'))
        self.assertEqual(client.opener.calls[2][2]['required_signals'],["traces","metrics"])

    def test_advanced_evaluation_client_exposes_calibration_gate_and_sampling(self):
        class Opener:
            calls=[]
            def open(self,request,timeout):
                self.calls.append((request.get_method(),request.full_url,
                    json.loads(request.data) if request.data else None))
                return io.BytesIO(b'{}')
        client=SentinelClient('http://localhost','snt_fixture_secret'); client.opener=Opener()
        client.add_human_label('dataset','case-key','run','0.9','pass')
        client.calibrate_judge('experiment'); client.analyze_experiments(['one','two'])
        client.create_release_gate('release-key',['one','two'],calibration_id='calibration')
        client.set_online_evaluation_policy('dataset','case-key','0.1'); client.sample_run_for_evaluation('run')
        self.assertEqual([item[0] for item in client.opener.calls],['POST','POST','POST','POST','PUT','POST'])
        self.assertEqual(client.opener.calls[3][2]['calibration_id'],'calibration')

    def test_product_operations_client_exposes_alert_deployment_and_lab_calls(self):
        class Opener:
            calls=[]
            def open(self,request,timeout):
                self.calls.append((request.get_method(),request.full_url,
                    json.loads(request.data) if request.data else None))
                return io.BytesIO(b'{}')
        client=SentinelClient('http://localhost','snt_fixture_secret'); client.opener=Opener()
        client.alert_policy(); client.set_alert_policy(failed_run_threshold=5)
        client.evaluate_alerts(); client.alerts('open'); client.acknowledge_alert('alert')
        client.create_deployment_environment('production','Production'); client.deployment_environments()
        client.approve_deployment('environment','gate','a'*64,'v1'); client.deployments()
        client.update_deployment('deployment','deployed')
        client.schedule_lab_campaign('security','standard'); client.lab_campaigns()
        client.claim_lab_campaign(); client.complete_lab_campaign('campaign',passed=True,
            checks_run=4,checks_failed=0,duration_ms=20)
        self.assertEqual([call[0] for call in client.opener.calls],
            ['GET','PUT','POST','GET','POST','POST','GET','POST','GET','POST','POST','GET','POST','POST'])
        self.assertTrue(client.opener.calls[3][1].endswith('/v1/alerts?status=open'))
        self.assertEqual(client.opener.calls[7][2]['artifact_digest'],'a'*64)
