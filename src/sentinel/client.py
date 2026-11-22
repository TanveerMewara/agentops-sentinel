"""Small HTTP client for independent agents using Sentinel's server-side policies."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class SentinelError(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Sentinel request failed (HTTP {status}).")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def validate_api_url(base_url):
    parsed = urlsplit(base_url)
    loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use an HTTP(S) API base URL without credentials, query, or fragment.")
    if parsed.scheme == "http" and not loopback:
        raise ValueError("Use HTTPS outside localhost.")
    return base_url.rstrip("/")


class SentinelClient:
    def __init__(self, base_url, api_key, *, timeout=15):
        self.base_url = validate_api_url(base_url)
        if not api_key.startswith("snt_") or timeout <= 0:
            raise ValueError("Supply a Sentinel API key and positive timeout.")
        self._api_key = api_key
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, body=None, *, method=None):
        if not path.startswith("/v1/"):
            raise ValueError("Client requests must use a Sentinel /v1/ endpoint.")
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url + path, data=data,
            headers={"X-API-Key": self._api_key, "Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            status = error.code
            error.close()
            raise SentinelError(status) from None
        except (URLError, TimeoutError, OSError, ValueError):
            # A timeout after a write can mean the action succeeded. Never retry
            # implicitly: replay the same operation key or reconcile at the server.
            raise SentinelError(0) from None

    def identity(self):
        return self.request("/v1/me")

    def register_agent(self, slug, display_name, description=""):
        return self.request("/v1/agents", {"slug": slug, "display_name": display_name, "description": description})

    def create_version(self, agent_id, version, instructions, model_alias="external_agent", max_steps=12):
        return self.request(f"/v1/agents/{agent_id}/versions", {"version": version,
            "instructions": instructions, "model_alias": model_alias, "max_steps": max_steps})

    def create_run(self, agent_version_id, idempotency_key, input_payload):
        return self.request("/v1/runs", {"agent_version_id": agent_version_id,
            "idempotency_key": idempotency_key, "input": input_payload})

    def reserve_tool(self, run_id, tool_id, idempotency_key, arguments):
        return self.request(f"/v1/runs/{run_id}/tool-calls", {"tool_id": tool_id,
            "idempotency_key": idempotency_key, "arguments": arguments})

    def complete_run(self, run_id):
        return self.request(f"/v1/runs/{run_id}/complete", {})

    def timeline(self, run_id):
        return self.request(f"/v1/runs/{run_id}/timeline")

    def submit_external_trace(self, run_id, evidence):
        return self.request(f"/v1/runs/{run_id}/external-trace", evidence)

    def submit_otlp_trace(self, run_id, otlp, output, idempotency_key, *,
                          trace_id=None, source="opentelemetry",
                          reported_status="succeeded"):
        body = {"schema_version": 1, "idempotency_key": idempotency_key,
            "source": source, "reported_status": reported_status,
            "output": output, "otlp": otlp}
        if trace_id is not None:
            body["trace_id"] = trace_id
        return self.request(f"/v1/runs/{run_id}/external-trace/otlp", body)

    def finalize_otlp_trace(self, run_id, output, idempotency_key, *,
                            reported_status="succeeded"):
        return self.request(f"/v1/runs/{run_id}/external-trace/otlp/finalize", {
            "idempotency_key": idempotency_key,
            "reported_status": reported_status, "output": output})

    def external_trace(self, run_id, *, include_output=False):
        suffix = "?include_output=true" if include_output else ""
        return self.request(f"/v1/runs/{run_id}/external-trace{suffix}")

    def telemetry(self, run_id):
        return self.request(f"/v1/runs/{run_id}/telemetry")

    def telemetry_policy(self):
        return self.request("/v1/telemetry/policy")

    def set_telemetry_policy(self, retention_days, required_signals, *,
                             require_token_usage=False, require_cost=False):
        return self.request("/v1/telemetry/policy", {
            "retention_days": retention_days, "required_signals": required_signals,
            "require_token_usage": require_token_usage, "require_cost": require_cost},
            method="PUT")

    def add_rate_card(self, pricing_key, input_usd_per_million,
                      output_usd_per_million):
        return self.request("/v1/telemetry/rate-cards", {
            "pricing_key": pricing_key,
            "input_usd_per_million": str(input_usd_per_million),
            "output_usd_per_million": str(output_usd_per_million)})

    def rate_cards(self):
        return self.request("/v1/telemetry/rate-cards")

    def purge_expired_telemetry(self):
        return self.request("/v1/telemetry/retention/purge", {})

    def delete_run_telemetry(self, run_id):
        return self.request(f"/v1/runs/{run_id}/telemetry", method="DELETE")

    def engagement(self, run_id):
        return self.request(f"/v1/runs/{run_id}/engagement")

    def evaluate(self, dataset_id, idempotency_key, bindings, min_pass_rate=1.0):
        return self.request("/v1/evaluations/experiments", {"dataset_id": dataset_id,
            "idempotency_key": idempotency_key, "bindings": bindings, "min_pass_rate": min_pass_rate})

    def add_human_label(self,dataset_id,case_key,run_id,score,label):
        return self.request('/v1/evaluations/human-labels',{'dataset_id':dataset_id,
            'case_key':case_key,'run_id':run_id,'score':str(score),'label':label})

    def calibrate_judge(self,experiment_id,*,min_labels=3,max_mean_absolute_error=0.2,
                        min_label_agreement=0.8):
        return self.request('/v1/evaluations/calibrations',{'experiment_id':experiment_id,
            'min_labels':min_labels,'max_mean_absolute_error':max_mean_absolute_error,
            'min_label_agreement':min_label_agreement})

    def analyze_experiments(self,experiment_ids):
        return self.request('/v1/evaluations/analysis',{'experiment_ids':experiment_ids})

    def create_release_gate(self,idempotency_key,experiment_ids,*,calibration_id=None,
                            baseline_experiment_ids=None,min_mean_pass_rate=0.9,
                            max_pass_rate_stddev=0.05,max_regression=0.02,require_held_out=True):
        body={'idempotency_key':idempotency_key,'experiment_ids':experiment_ids,
            'baseline_experiment_ids':baseline_experiment_ids or [],'min_mean_pass_rate':min_mean_pass_rate,
            'max_pass_rate_stddev':max_pass_rate_stddev,'max_regression':max_regression,
            'require_held_out':require_held_out}
        if calibration_id is not None: body['calibration_id']=calibration_id
        return self.request('/v1/evaluations/release-gates',body)

    def set_online_evaluation_policy(self,dataset_id,case_key,sample_rate,*,daily_limit=100,enabled=True):
        return self.request('/v1/evaluations/online-policy',{'dataset_id':dataset_id,
            'case_key':case_key,'sample_rate':str(sample_rate),'daily_limit':daily_limit,'enabled':enabled},method='PUT')

    def sample_run_for_evaluation(self,run_id):
        return self.request(f'/v1/runs/{run_id}/evaluation-sample',{})

    def alert_policy(self):
        return self.request('/v1/alerts/policy')

    def set_alert_policy(self, *, telemetry_incomplete=True,
                         release_gate_failed=True, failed_run_threshold=3):
        return self.request('/v1/alerts/policy', {
            'telemetry_incomplete': telemetry_incomplete,
            'release_gate_failed': release_gate_failed,
            'failed_run_threshold': failed_run_threshold}, method='PUT')

    def evaluate_alerts(self):
        return self.request('/v1/alerts/evaluate', {})

    def alerts(self, status=None):
        suffix = f'?status={status}' if status else ''
        return self.request('/v1/alerts' + suffix)

    def acknowledge_alert(self, alert_id):
        return self.request(f'/v1/alerts/{alert_id}/acknowledge', {})

    def create_deployment_environment(self, slug, display_name):
        return self.request('/v1/deployments/environments', {
            'slug': slug, 'display_name': display_name})

    def deployment_environments(self):
        return self.request('/v1/deployments/environments')

    def approve_deployment(self, environment_id, release_gate_id,
                           artifact_digest, version):
        return self.request('/v1/deployments', {
            'environment_id': environment_id, 'release_gate_id': release_gate_id,
            'artifact_digest': artifact_digest, 'version': version})

    def deployments(self):
        return self.request('/v1/deployments')

    def update_deployment(self, deployment_id, status):
        return self.request(f'/v1/deployments/{deployment_id}/status',
                            {'status': status})

    def schedule_lab_campaign(self, campaign_type, profile):
        return self.request('/v1/labs/campaigns', {
            'campaign_type': campaign_type, 'profile': profile})

    def lab_campaigns(self):
        return self.request('/v1/labs/campaigns')

    def claim_lab_campaign(self):
        return self.request('/v1/labs/campaigns/claim', {})

    def complete_lab_campaign(self, campaign_id, *, passed, checks_run,
                              checks_failed, duration_ms):
        return self.request(f'/v1/labs/campaigns/{campaign_id}/complete', {
            'passed': passed, 'checks_run': checks_run,
            'checks_failed': checks_failed, 'duration_ms': duration_ms})
