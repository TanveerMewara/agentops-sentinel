'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { BellRing, Boxes, CloudCog, FlaskConical, RefreshCw, Rocket, ShieldCheck, Users } from 'lucide-react';

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type Props = { connected: boolean; onConnect: () => void; request: Request };
type Alert = { alert_id: string; alert_type: string; severity: string; summary: Record<string, unknown>; status: string; created_at: string };
type Environment = { environment_id: string; slug: string; display_name: string };
type Deployment = { deployment_id: string; version: string; status: string; artifact_digest: string; created_at: string };
type Campaign = { campaign_id: string; campaign_type: string; profile: string; status: string; report?: { checks_run: number; checks_failed: number }; created_at: string };
type Member = { member_id: string; handle: string; display_name: string; role: string; status: string };
type Tool = { tool_id: string; name: string; version: string; risk_level: string; approval_mode: string };
type Agent = { agent_id: string; display_name: string };
type Provider = { provider_id: string; model_alias: string; provider: string; model_id: string; key_hint: string; status: string };
type Gate = { release_gate_id: string; report: { passed: boolean }; created_at: string };
type Policy = { telemetry_incomplete: boolean; release_gate_failed: boolean; failed_run_threshold: number };

const emptyPolicy: Policy = { telemetry_incomplete: true, release_gate_failed: true, failed_run_threshold: 3 };
const safeSchema = { type: 'object', properties: {}, required: [], additionalProperties: false };

export default function ControlCenter({ connected, onConnect, request }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [gates, setGates] = useState<Gate[]>([]);
  const [policy, setPolicy] = useState<Policy>(emptyPolicy);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setBusy('refresh'); setMessage('');
    const calls = await Promise.allSettled([
      request<Alert[]>('/v1/alerts'), request<Environment[]>('/v1/deployments/environments'),
      request<Deployment[]>('/v1/deployments'), request<Campaign[]>('/v1/labs/campaigns'),
      request<Member[]>('/v1/onboarding/members'), request<Tool[]>('/v1/tools'),
      request<Agent[]>('/v1/agents'), request<Provider[]>('/v1/model-providers'),
      request<Gate[]>('/v1/evaluations/release-gates'), request<Policy>('/v1/alerts/policy'),
    ]);
    const setters = [setAlerts, setEnvironments, setDeployments, setCampaigns, setMembers, setTools, setAgents, setProviders, setGates, setPolicy] as Array<(value: never) => void>;
    calls.forEach((result, index) => { if (result.status === 'fulfilled') setters[index](result.value as never); });
    const failures = calls.filter((result) => result.status === 'rejected').length;
    if (failures) setMessage(`${failures} control-center section${failures === 1 ? '' : 's'} could not be read with this role.`);
    setBusy('');
  }, [connected, request]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function act(name: string, action: () => Promise<unknown>, success: string) {
    setBusy(name); setMessage('');
    try { await action(); setMessage(success); await load(); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : 'The action could not be completed.'); setBusy(''); }
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await act('policy', () => request('/v1/alerts/policy', { method: 'PUT', body: JSON.stringify(policy) }), 'Alert policy saved.');
  }

  async function createEnvironment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    await act('environment', () => request('/v1/deployments/environments', { method: 'POST', body: JSON.stringify({ slug: values.get('slug'), display_name: values.get('display_name') }) }), 'Deployment environment registered.');
    form.reset();
  }

  async function scheduleCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    await act('campaign', () => request('/v1/labs/campaigns', { method: 'POST', body: JSON.stringify({ campaign_type: values.get('campaign_type'), profile: values.get('profile') }) }), 'Lab campaign queued for a worker.');
  }

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    setBusy('invite'); setMessage('');
    try {
      const result = await request<{ token: string }>('/v1/onboarding/invitations', { method: 'POST', body: JSON.stringify({ handle: values.get('handle'), role: values.get('role'), expires_in_hours: 24 }) });
      setMessage(`Invitation created. Copy this one-time token now: ${result.token}`);
      setBusy('');
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : 'The invitation could not be created.'); setBusy(''); }
  }

  async function registerTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    await act('tool', () => request('/v1/tools', { method: 'POST', body: JSON.stringify({ name: values.get('name'), version: values.get('version'), description: values.get('description'), input_schema: safeSchema, output_schema: safeSchema, risk_level: values.get('risk_level'), approval_mode: values.get('approval_mode') }) }), 'Tool contract registered.');
  }

  async function grantTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget);
    await act('grant', () => request(`/v1/agents/${values.get('agent_id')}/tools/${values.get('tool_id')}`, { method: 'POST', body: JSON.stringify({ max_calls_per_run: Number(values.get('max_calls_per_run')) }) }), 'Tool granted to the selected agent.');
  }

  async function configureProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    await act('provider', () => request('/v1/model-providers/openai', { method: 'POST', body: JSON.stringify({ model_alias: values.get('model_alias'), model_id: values.get('model_id'), api_key: values.get('api_key') }) }), 'Provider configured; only its masked key hint is readable.');
    form.reset();
  }

  return <section className="control-center panel" id="control-center" aria-labelledby="control-center-title">
    <header className="control-center-head"><div><p className="eyebrow">PRODUCT OPERATIONS</p><h2 id="control-center-title">Configure, review, release, and test</h2><p>One workspace for reusable agent controls. Every action below uses the live Sentinel API.</p></div><button className="secondary-button" disabled={busy === 'refresh'} onClick={connected ? load : onConnect}><RefreshCw size={15} className={busy === 'refresh' ? 'spin' : ''} />{connected ? 'Refresh' : 'Connect'}</button></header>
    {!connected ? <div className="control-empty"><ShieldCheck size={27} /><strong>Connect your workspace to operate Sentinel</strong><p>No fictional operational result is shown here.</p><button className="primary-button" onClick={onConnect}>Connect API</button></div> : <>
      {message && <p className="control-message" role="status">{message}</p>}
      <div className="control-metrics"><span><BellRing size={16} /><strong>{alerts.filter((item) => item.status === 'open').length}</strong>Open alerts</span><span><Rocket size={16} /><strong>{deployments.length}</strong>{environments.length} env · deployments</span><span><FlaskConical size={16} /><strong>{campaigns.length}</strong>Lab campaigns</span><span><Users size={16} /><strong>{members.length}</strong>Members</span></div>
      <div className="control-grid">
        <article><h3><BellRing size={16} /> Alert policy and inbox</h3><form onSubmit={savePolicy}><label><input type="checkbox" checked={policy.telemetry_incomplete} onChange={(e) => setPolicy({ ...policy, telemetry_incomplete: e.target.checked })} />Missing telemetry</label><label><input type="checkbox" checked={policy.release_gate_failed} onChange={(e) => setPolicy({ ...policy, release_gate_failed: e.target.checked })} />Failed release gates</label><label>Failed runs per hour<input type="number" min="1" max="1000" value={policy.failed_run_threshold} onChange={(e) => setPolicy({ ...policy, failed_run_threshold: Number(e.target.value) })} /></label><div><button className="secondary-button" disabled={!!busy}>Save policy</button><button type="button" className="secondary-button" disabled={!!busy} onClick={() => act('evaluate', () => request('/v1/alerts/evaluate', { method: 'POST', body: '{}' }), 'Alert evaluation completed.')}>Evaluate now</button></div></form><div className="control-list">{alerts.slice(0, 5).map((item) => <div key={item.alert_id}><span className={`control-status ${item.severity}`}>{item.severity}</span><strong>{item.alert_type.replaceAll('_', ' ')}</strong><small>{item.status}</small>{item.status === 'open' && <button disabled={!!busy} onClick={() => act('ack', () => request(`/v1/alerts/${item.alert_id}/acknowledge`, { method: 'POST', body: '{}' }), 'Alert acknowledged.')}>Acknowledge</button>}</div>)}{alerts.length === 0 && <p>No alerts found.</p>}</div></article>
        <article><h3><Rocket size={16} /> Release and deployments</h3><form onSubmit={createEnvironment}><label>Environment slug<input name="slug" required pattern="[a-z][a-z0-9_-]{2,49}" placeholder="production" /></label><label>Display name<input name="display_name" required minLength={2} placeholder="Production" /></label><button className="secondary-button" disabled={!!busy}>Register environment</button></form><div className="control-list">{gates.slice(0, 3).map((gate) => <div key={gate.release_gate_id}><span className={`control-status ${gate.report.passed ? 'passed' : 'failed'}`}>{gate.report.passed ? 'passed' : 'blocked'}</span><strong>Release gate</strong><small>{gate.release_gate_id.slice(0, 8)}</small></div>)}{deployments.slice(0, 4).map((item) => <div key={item.deployment_id}><span className="control-status">{item.status}</span><strong>{item.version}</strong><small>{item.artifact_digest.slice(0, 10)}â€¦</small></div>)}</div><p className="control-note">The API accepts a deployment only when its referenced release gate passed.</p></article>
        <article><h3><FlaskConical size={16} /> Failure and security labs</h3><form onSubmit={scheduleCampaign}><label>Lab<select name="campaign_type"><option value="failure">Failure injection</option><option value="security">Security checks</option></select></label><label>Bounded profile<select name="profile"><option value="standard">Standard</option><option value="extended">Extended</option></select></label><button className="secondary-button" disabled={!!busy}>Queue campaign</button></form><div className="control-list">{campaigns.slice(0, 6).map((item) => <div key={item.campaign_id}><span className="control-status">{item.status}</span><strong>{item.campaign_type} Â· {item.profile}</strong><small>{item.report ? `${item.report.checks_run} checks / ${item.report.checks_failed} failed` : 'Awaiting worker'}</small></div>)}{campaigns.length === 0 && <p>No campaigns queued.</p>}</div></article>
        <article><h3><Users size={16} /> Team onboarding</h3><form onSubmit={invite}><label>Handle<input name="handle" required pattern="[a-z][a-z0-9_.-]{2,49}" placeholder="alex.dev" /></label><label>Role<select name="role"><option value="developer">Developer</option><option value="reviewer">Reviewer</option><option value="worker">Worker</option><option value="admin">Administrator</option></select></label><button className="secondary-button" disabled={!!busy}>Create one-time invite</button></form><div className="control-list">{members.slice(0, 6).map((item) => <div key={item.member_id}><span className="control-status">{item.role}</span><strong>{item.display_name}</strong><small>{item.handle} Â· {item.status}</small></div>)}{members.length === 0 && <p>No browser members found.</p>}</div></article>
        <article><h3><Boxes size={16} /> Tool contracts and grants</h3><form onSubmit={registerTool}><label>Name<input name="name" required pattern="[a-z][a-z0-9_]{2,63}" placeholder="search_records" /></label><label>Version<input name="version" required pattern="[0-9]+\.[0-9]+\.[0-9]+" defaultValue="1.0.0" /></label><label>Description<input name="description" required maxLength={500} placeholder="What this tool is allowed to do" /></label><label>Risk<select name="risk_level"><option>low</option><option>medium</option><option>high</option></select></label><label>Approval<select name="approval_mode"><option value="risk_based">Risk based</option><option value="always">Always</option><option value="never">Never</option></select></label><button className="secondary-button" disabled={!!busy}>Register contract</button></form><form onSubmit={grantTool}><label>Agent<select name="agent_id" required><option value="">Choose</option>{agents.map((item) => <option key={item.agent_id} value={item.agent_id}>{item.display_name}</option>)}</select></label><label>Tool<select name="tool_id" required><option value="">Choose</option>{tools.map((item) => <option key={item.tool_id} value={item.tool_id}>{item.name} Â· {item.version}</option>)}</select></label><label>Calls per run<input name="max_calls_per_run" type="number" min="1" max="100" defaultValue="1" required /></label><button className="secondary-button" disabled={!!busy}>Grant tool</button></form></article>
        <article><h3><CloudCog size={16} /> Model providers</h3><form onSubmit={configureProvider}><label>Model alias<input name="model_alias" required pattern="[a-z][a-z0-9_-]{2,63}" placeholder="reasoning_primary" /></label><label>OpenAI model ID<input name="model_id" required maxLength={100} placeholder="gpt-5.4" /></label><label>Provider API key<input name="api_key" type="password" required minLength={20} maxLength={500} autoComplete="new-password" /></label><button className="secondary-button" disabled={!!busy}>Encrypt and save</button></form><div className="control-list">{providers.map((item) => <div key={item.provider_id}><span className="control-status">{item.status}</span><strong>{item.model_alias} â†’ {item.model_id}</strong><small>{item.provider} Â· {item.key_hint}</small></div>)}{providers.length === 0 && <p>No managed model provider configured.</p>}</div><p className="control-note">Secrets are write-only. The dashboard receives only a masked hint.</p></article>
      </div>
    </>}
  </section>;
}

