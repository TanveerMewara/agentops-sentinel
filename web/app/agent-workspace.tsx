'use client';

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, Bot, ChevronLeft, ChevronRight, Layers, Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import ExternalTraceInspector from './external-trace-inspector';

type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };
type Agent = { agent_id: string; display_name: string; slug: string; status: string; description?: string };
type Version = { agent_version_id: string; version: string; model_alias: string; max_steps: number };
type Tool = { tool_id: string; name: string; version: string; risk_level: string; approval_mode: string };
type Run = { run_id: string; agent_id: string; agent_version_id: string; status: string; steps_used: number; max_steps: number; idempotency_key: string };

function AgentShelf({ title, note, agents, runs, selectedId, disabled, onSelect }: {
  title: string; note: string; agents: Agent[]; runs: Run[]; selectedId: string; disabled: boolean; onSelect: (agent: Agent) => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  function scroll(direction: number) {
    rail.current?.scrollBy({ left: direction * rail.current.clientWidth * .8, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }
  return <section className="agent-shelf" aria-label={title}>
    <div className="agent-shelf-heading"><div><h3>{title}<span>{agents.length}</span></h3><p>{note}</p></div><div className="agent-rail-controls"><button type="button" aria-label={`Scroll ${title} left`} onClick={() => scroll(-1)}><ChevronLeft size={18} /></button><button type="button" aria-label={`Scroll ${title} right`} onClick={() => scroll(1)}><ChevronRight size={18} /></button></div></div>
    {agents.length === 0 ? <p className="agent-shelf-empty">No agents in this row.</p> : <div className="agent-rail" ref={rail}>{agents.map((agent) => {
      const recent = runs.find((run) => run.agent_id === agent.agent_id);
      const palette = [...agent.agent_id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 4;
      return <button type="button" className={`agent-poster palette-${palette} ${selectedId === agent.agent_id ? 'agent-poster-selected' : ''}`} key={agent.agent_id} disabled={disabled} onClick={() => onSelect(agent)} aria-pressed={selectedId === agent.agent_id}>
        <span className="agent-poster-art"><span className="agent-poster-grid" /><Bot size={62} strokeWidth={1} /><span className="agent-poster-monogram">{agent.display_name.slice(0, 2).toUpperCase()}</span><span className={`agent-state ${agent.status === 'active' ? 'agent-state-active' : ''}`}>{agent.status}</span><span className="agent-poster-open"><ArrowRight size={18} /></span></span>
        <span className="agent-poster-caption"><strong>{agent.display_name}</strong><span>{agent.slug}</span><small>{recent ? `Latest loaded run: ${recent.status.replaceAll('_', ' ')}` : 'No runs in loaded history'}</small></span>
      </button>;
    })}</div>}
  </section>;
}

// Connection changes remount the session so private records and pending results
// from one organization cannot appear in the next organization's workspace.
export default function AgentWorkspace(props: Props) {
  const [session, setSession] = useState({ request: props.request, connected: props.connected, generation: 0 });
  if (session.request !== props.request || session.connected !== props.connected) {
    setSession({ request: props.request, connected: props.connected, generation: session.generation + 1 });
  }
  return <WorkspaceSession key={session.generation} {...props} />;
}

function WorkspaceSession({ connected, onConnect, request }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [versions, setVersions] = useState<Version[]>([]);
  const [agentId, setAgentId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [input, setInput] = useState('{}');
  const [runKey, setRunKey] = useState('');
  const [role, setRole] = useState('');
  const [busy, setBusy] = useState(connected);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [showManager, setShowManager] = useState(false);
  const [traceRunId, setTraceRunId] = useState('');
  const featured = agents.find((agent) => agent.agent_id === agentId) ?? agents[0];
  const recentAgents = [...new Set(runs.map((run) => run.agent_id))].map((id) => agents.find((agent) => agent.agent_id === id)).filter((agent): agent is Agent => Boolean(agent));
  const attentionAgents = agents.filter((agent) => runs.some((run) => run.agent_id === agent.agent_id && ['failed', 'needs_review'].includes(run.status)));
  const canWrite = ['admin', 'developer'].includes(role);

  function selectAgent(agent: Agent) {
    if (agentId !== agent.agent_id) { setAgentId(agent.agent_id); setVersions([]); setVersionId(''); setRunKey(''); }
    setShowManager(true);
    requestAnimationFrame(() => document.getElementById('agent-manager')?.scrollIntoView({ block: 'start' }));
  }

  const fetchData = useCallback(async () => {
    const [a, t, r, identity] = await Promise.all([
      request('/v1/agents'), request('/v1/tools'), request('/v1/runs?limit=100'), request('/v1/me'),
    ]);
    return { agents: a as Agent[], tools: t as Tool[], runs: r as Run[], role: (identity as { role: string }).role };
  }, [request]);
  useEffect(() => {
    let active = true;
    if (connected) fetchData().then((data) => {
      if (active) { setAgents(data.agents); setTools(data.tools); setRuns(data.runs); setRole(data.role); }
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load workspace.'); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [connected, fetchData]);
  useEffect(() => {
    let active = true;
    if (agentId) request(`/v1/agents/${agentId}/versions`).then((data) => {
      if (active) setVersions(data as Version[]);
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load versions.'); });
    return () => { active = false; };
  }, [agentId, request]);

  async function refresh() {
    setBusy(true); setError(null);
    try { const data = await fetchData(); setAgents(data.agents); setTools(data.tools); setRuns(data.runs); setRole(data.role); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not refresh workspace.'); }
    finally { setBusy(false); }
  }
  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setNotice(null);
    const form = event.currentTarget;
    const values = new FormData(form);
    try {
      const agent = await request('/v1/agents', { method: 'POST', body: JSON.stringify({
        slug: values.get('slug'), display_name: values.get('display_name'), description: values.get('description'),
      }) }) as Agent;
      setAgents(await request('/v1/agents') as Agent[]);
      setAgentId(agent.agent_id); setVersions([]); setVersionId(''); setRunKey('');
      setNotice('Agent registered. Add an immutable version before creating a run.'); form.reset();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not register agent.'); }
    finally { setBusy(false); }
  }
  async function createVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setNotice(null);
    const values = new FormData(event.currentTarget);
    try {
      const version = await request(`/v1/agents/${agentId}/versions`, { method: 'POST', body: JSON.stringify({
        version: values.get('version'), instructions: values.get('instructions'), model_alias: values.get('model_alias'), max_steps: Number(values.get('max_steps')),
      }) }) as Version;
      setVersions(await request(`/v1/agents/${agentId}/versions`) as Version[]);
      setVersionId(version.agent_version_id); setRunKey(''); setNotice('Immutable version saved. No agent was executed.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save version.'); }
    finally { setBusy(false); }
  }
  async function createRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setNotice(null);
    const key = runKey || `workspace-${crypto.randomUUID()}`;
    try {
      const payload: unknown = JSON.parse(input);
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Run input must be a JSON object.');
      setRunKey(key);
      const result = await request('/v1/runs', { method: 'POST', body: JSON.stringify({
        idempotency_key: key, agent_version_id: versionId, input: payload,
      }) }) as Run;
      setNotice(`Run ${result.run_id} recorded as ${result.status}. Execute it through your agent integration; no agent was launched here.`);
      setRuns(await request('/v1/runs?limit=100') as Run[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Run creation could not be confirmed. Inspect saved runs before starting a new request.'); }
    finally { setBusy(false); }
  }

  return <section className="platform-evidence agent-catalog" id="agent-workspace" aria-labelledby="agent-heading">
    <div className="agent-feature">
      <div className="agent-feature-art" aria-hidden="true"><div className="agent-orbit agent-orbit-one" /><div className="agent-orbit agent-orbit-two" /><div className="agent-feature-emblem"><ShieldCheck size={112} strokeWidth={.8} /></div><span className="agent-feature-word">SENTINEL</span></div>
      <div className="agent-feature-content"><p className="agent-kicker"><span />{featured ? 'FEATURED AGENT' : 'YOUR AGENT CONTROL PLANE'}</p><h2 id="agent-heading">{featured?.display_name ?? <>Big ideas.<br />Accountable agents.</>}</h2><div className="agent-feature-tags"><span><ShieldCheck size={13} />{featured ? `Registry: ${featured.status}` : 'Human oversight'}</span><span>Versioned configurations</span><span>Execution evidence</span></div><p className="agent-feature-description">{featured?.description || 'A home for every agent you build. Explore your fleet, inspect its work, and turn saved runs into evidence you can trust.'}</p><div className="agent-feature-actions"><button className="agent-main-action" disabled={busy} onClick={() => featured ? selectAgent(featured) : onConnect()}><Layers size={17} />{featured ? 'Inspect agent' : 'Connect your agents'}</button><button className="agent-secondary-action" disabled={busy} onClick={() => { if (!connected) { onConnect(); return; } setShowManager(true); requestAnimationFrame(() => document.getElementById('agent-manager')?.scrollIntoView({ block: 'start' })); }}><Plus size={17} />Register an agent</button></div><p className="agent-feature-footnote">{connected ? 'Live registry · run creation is separate from execution' : 'Connect your API to see live agents · no fabricated results'}</p></div>
    </div>
    <div className="agent-catalog-toolbar"><div><span className="agent-kicker">YOUR LIBRARY</span><h3>Built by you. Governed by Sentinel.</h3></div><button className="agent-secondary-action" onClick={connected ? refresh : onConnect} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''} />Refresh library</button></div>
    {!connected ? <div className="evidence-results"><h3>Connect your first agent</h3><p className="evidence-note">Use the Sentinel API or Python client with your own agent. EstateFlow and support triage are example integrations. No sample run is presented as a real result.</p><button className="primary-button" onClick={onConnect}>Connect Sentinel API</button></div> : <>
      {busy && agents.length === 0 && <p className="evidence-note" role="status">Loading your agent library…</p>}
      <AgentShelf title="Your agent fleet" note="All registered agents. Select a card to inspect its configuration." agents={agents} runs={runs} selectedId={agentId} disabled={busy} onSelect={selectAgent} />
      <AgentShelf title="Recently in action" note="Agents appearing in the latest 100 saved runs." agents={recentAgents} runs={runs} selectedId={agentId} disabled={busy} onSelect={selectAgent} />
      <AgentShelf title="Worth a closer look" note="Agents with failed or review-required runs in loaded history; this is not a safety score." agents={attentionAgents} runs={runs} selectedId={agentId} disabled={busy} onSelect={selectAgent} />
      <div className="evidence-metrics workspace-metrics"><div><strong>{agents.length}</strong><span>Registered agents</span></div><div><strong>{tools.length}</strong><span>Registered tool contracts</span></div><div><strong>{runs.length}</strong><span>Loaded runs (up to 100)</span></div><div><strong>{runs.filter((r) => ['queued', 'running'].includes(r.status)).length}</strong><span>Queued/running in loaded records</span></div></div>
      <div className="agent-manager-toggle"><button className="agent-secondary-action" aria-expanded={showManager} aria-controls="agent-manager" onClick={() => setShowManager(!showManager)}>{showManager ? 'Hide configuration' : 'Open agent configuration'}<ChevronRight size={16} /></button></div>
      {showManager && <div className="agent-manager panel" id="agent-manager"><div className="evidence-grid"><form onSubmit={register}><h3>Register an agent</h3><label>Display name<input name="display_name" required maxLength={100} placeholder="Support triage" disabled={!canWrite || busy} /></label><label>Unique slug<input name="slug" required pattern="[a-z][a-z0-9_]{2,63}" placeholder="support_triage" disabled={!canWrite || busy} /></label><label>Description<input name="description" maxLength={500} disabled={!canWrite || busy} /></label><button className="secondary-button" disabled={!canWrite || busy}>Register agent</button></form>
      <form onSubmit={createVersion}><h3>Save an agent version</h3><label>Registered agent<select value={agentId} required disabled={busy} onChange={(e) => { setAgentId(e.target.value); setVersions([]); setVersionId(''); setRunKey(''); }}><option value="">Choose an agent</option>{agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.display_name} · {a.status}</option>)}</select></label><div className="evidence-inline"><label>Version<input name="version" defaultValue="1.0.0" pattern="[0-9]+\.[0-9]+\.[0-9]+" required disabled={!canWrite || busy} /></label><label>Step budget<input name="max_steps" type="number" min={1} max={100} defaultValue={12} required disabled={!canWrite || busy} /></label></div><label>Model alias<input name="model_alias" defaultValue="external_agent" pattern="[a-z][a-z0-9_-]{2,63}" required disabled={!canWrite || busy} /></label><label>Instructions<textarea name="instructions" required maxLength={20000} disabled={!canWrite || busy} placeholder="Describe the externally executed agent and its intended behavior." /></label><p className="evidence-note">An external alias is configuration metadata; it does not install a model provider or execution adapter.</p><button className="secondary-button" disabled={!canWrite || busy || !agentId}>Save immutable version</button></form></div>
      <form className="evidence-results" onSubmit={createRun}><h3>Create a run record</h3><label>Version<select required value={versionId} disabled={!canWrite || busy} onChange={(e) => { setVersionId(e.target.value); setRunKey(''); }}><option value="">Choose an agent version</option>{versions.map((v) => <option key={v.agent_version_id} value={v.agent_version_id}>{v.version} · {v.model_alias} · {v.max_steps} steps</option>)}</select></label><label>Input JSON<textarea value={input} required disabled={!canWrite || busy} onChange={(e) => { setInput(e.target.value); setRunKey(''); }} /></label><label>Idempotency key<input value={runKey} disabled={!canWrite || busy} minLength={8} maxLength={200} placeholder="Generated on submission; keep for an uncertain response" onChange={(e) => setRunKey(e.target.value)} /></label><p className="evidence-note">Creation records input and freezes current tool permissions. It does not execute an arbitrary agent. Keep the key for replay; reconnecting or reloading clears this form. Do not put credentials or private buyer data in run input.</p><button className="primary-button" disabled={!canWrite || busy || !versionId}>Create run record</button></form>
      </div>}
      <div className="evidence-results"><h3>Saved runs</h3><p className="evidence-note">Showing up to 20 matches from the latest 100 loaded runs. Search checks all loaded records.</p><label>Search loaded runs<input id="agent-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Agent name, run ID, status or replay key" /></label>{runs.length === 0 ? <p className="evidence-note">No runs yet. Register an agent and integrate it through the API/client.</p> : <>{runs.filter((r) => `${agents.find((a) => a.agent_id === r.agent_id)?.display_name ?? r.agent_id} ${r.run_id} ${r.status} ${r.idempotency_key}`.toLowerCase().includes(query.toLowerCase())).slice(0, 20).map((r) => <div className="evidence-case" key={r.run_id}><strong>{agents.find((a) => a.agent_id === r.agent_id)?.display_name ?? r.agent_id} · {r.status}</strong><p><code>{r.run_id}</code><span>{r.steps_used}/{r.max_steps} steps</span></p><p className="evidence-note">Replay key: {r.idempotency_key}</p><button type="button" className="secondary-button" onClick={() => setTraceRunId(r.run_id)}>Inspect external evidence</button></div>)}{query && !runs.some((r) => `${agents.find((a) => a.agent_id === r.agent_id)?.display_name ?? r.agent_id} ${r.run_id} ${r.status} ${r.idempotency_key}`.toLowerCase().includes(query.toLowerCase())) && <p className="evidence-note">No matching loaded runs.</p>}</>}</div>
      <div className="evidence-results"><h3>Tool contracts</h3><p className="evidence-note">Registration defines a contract. Dispatch also requires an installed adapter and a grant frozen into the run.</p>{tools.length === 0 ? <p className="evidence-note">No tool contracts registered.</p> : tools.map((t) => <div className="evidence-case" key={t.tool_id}><strong>{t.name} · {t.version}</strong><p>{t.risk_level} risk · approval: {t.approval_mode}</p></div>)}</div>
      {traceRunId && <ExternalTraceInspector key={traceRunId} runId={traceRunId} request={request} canWrite={canWrite} />}
      {!canWrite && <p className="evidence-note workspace-metrics">Agent, version and run creation require an administrator or developer key.</p>}
    </>}
    {notice && <p className="evidence-note workspace-metrics" role="status">{notice}</p>}{error && <p className="property-error" role="alert">{error}</p>}
  </section>;
}
