'use client';

import {
  Activity, AlertTriangle, ArrowRight, Check, CheckCircle2, ChevronRight,
  CircleDot, Clock3, Command, Database, KeyRound, LayoutDashboard, ListFilter, CalendarDays,
  LockKeyhole, Menu, Play, Plus, RefreshCw, Search, Server, ShieldCheck,
  SlidersHorizontal, TerminalSquare, X,
} from 'lucide-react';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import PropertySearchPanel from './property-search';
import LeadIntakePanel from './lead-intake';
import './lead-intake.css';
import EngagementQueue from './engagement-queue';
import './engagement-queue.css';
import PlatformEvidence from './platform-evidence';
import './platform-evidence.css';
import AccessAdministration from './access-administration';
import './access-administration.css';
import OperationsOverview from './operations-overview';
import './operations-overview.css';
import ControlCenter from './control-center';
import './control-center.css';
import './navigation.css';
import ViewingCalendar from './viewing-calendar';
import './viewing-calendar.css';
import AgentWorkspace from './agent-workspace';
import './agent-workspace.css';

type OperationStatus = 'awaiting_approval' | 'authorized' | 'executing' | 'unknown' | 'succeeded' | 'failed' | 'needs_review' | 'rejected';
type Operation = {
  operation_id: string; idempotency_key: string; action_type: string;
  action: { customer: string; slot: string }; status: OperationStatus;
  external_id: string | null; last_error: string | null; created_at: string; updated_at: string;
};
type OperationEvent = {
  event_id: number; event_type: string; from_status: string | null;
  to_status: string; details: Record<string, unknown>; created_at: string;
};

const demoOperations: Operation[] = [
  { operation_id: '7c9221a4-5634-4d93-b4ab-ef1649838d31', idempotency_key: 'viewing-anika-20260910-01', action_type: 'book_viewing', action: { customer: 'Anika Sharma', slot: '12 Sep · 11:30 AM' }, status: 'needs_review', external_id: null, last_error: 'The provider accepted the request but the response was lost.', created_at: '2026-09-10T08:42:00Z', updated_at: '2026-09-10T08:44:12Z' },
  { operation_id: '0893fe7b-73b6-42a0-9047-9ed14f8018cd', idempotency_key: 'viewing-rohan-20260910-02', action_type: 'book_viewing', action: { customer: 'Rohan Mehta', slot: '12 Sep · 2:00 PM' }, status: 'awaiting_approval', external_id: null, last_error: null, created_at: '2026-09-10T08:31:00Z', updated_at: '2026-09-10T08:31:00Z' },
  { operation_id: '62e8e6b7-6733-4ca7-8f48-c45c16454f60', idempotency_key: 'viewing-mira-20260910-03', action_type: 'book_viewing', action: { customer: 'Mira Kapoor', slot: '13 Sep · 10:00 AM' }, status: 'succeeded', external_id: 'BK-48219', last_error: null, created_at: '2026-09-10T08:16:00Z', updated_at: '2026-09-10T08:19:32Z' },
  { operation_id: 'd4d360af-4ccb-49bc-ac88-978177c61c9c', idempotency_key: 'viewing-arjun-20260910-04', action_type: 'book_viewing', action: { customer: 'Arjun Rao', slot: '13 Sep · 4:30 PM' }, status: 'authorized', external_id: null, last_error: null, created_at: '2026-09-10T08:05:00Z', updated_at: '2026-09-10T08:07:14Z' },
];
const demoEvents: OperationEvent[] = [
  { event_id: 1, event_type: 'operation.created', from_status: null, to_status: 'awaiting_approval', details: {}, created_at: '2026-09-10T08:42:00Z' },
  { event_id: 2, event_type: 'approval.granted', from_status: 'awaiting_approval', to_status: 'authorized', details: { valid_for_seconds: 300 }, created_at: '2026-09-10T08:43:14Z' },
  { event_id: 3, event_type: 'execution.uncertain', from_status: 'executing', to_status: 'needs_review', details: { reason: 'response_lost' }, created_at: '2026-09-10T08:44:12Z' },
];
const statusMeta: Record<OperationStatus, { label: string; tone: string }> = {
  awaiting_approval: { label: 'Awaiting approval', tone: 'amber' }, authorized: { label: 'Authorized', tone: 'cyan' },
  executing: { label: 'Executing', tone: 'cyan' }, unknown: { label: 'Unknown outcome', tone: 'red' },
  succeeded: { label: 'Succeeded', tone: 'green' }, failed: { label: 'Failed', tone: 'red' },
  needs_review: { label: 'Needs review', tone: 'red' }, rejected: { label: 'Rejected', tone: 'muted' },
};
const shortId = (value: string) => value.split('-')[0].toUpperCase();
function relativeTime(value: string) {
  const seconds = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
function StatusBadge({ status }: { status: OperationStatus }) {
  const meta = statusMeta[status];
  return <span className={`status-badge status-${meta.tone}`}><span className="status-dot" />{meta.label}</span>;
}

// NEXT_PUBLIC_SENTINEL_API_URL may be absolute (https://api.example.com) or a
// same-origin path such as /sentinel-api (served by the rewrite in next.config.ts).
function defaultApiUrl() {
  const configured = process.env.NEXT_PUBLIC_SENTINEL_API_URL?.trim();
  if (!configured) return 'http://127.0.0.1:8020';
  if (configured.startsWith('/') && typeof window !== 'undefined') return `${window.location.origin}${configured}`;
  return configured;
}

export default function Home() {
  const [apiUrl, setApiUrl] = useState(defaultApiUrl);
  const [apiKey, setApiKey] = useState('');
  const [authMode, setAuthMode] = useState<'key' | 'member'>('key');
  const [connected, setConnected] = useState(false);
  const [operations, setOperations] = useState<Operation[]>(demoOperations);
  const [selectedId, setSelectedId] = useState(demoOperations[0].operation_id);
  const [events, setEvents] = useState<OperationEvent[]>(demoEvents);
  const [filter, setFilter] = useState<'all' | 'attention' | 'pending' | 'active' | 'complete'>('all');
  const [navigation, setNavigation] = useState('overview');
  const [query, setQuery] = useState('');
  const [showConnect, setShowConnect] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const showExamples = ['examples', 'operations', 'approvals', 'leads', 'calendar', 'engagement'].includes(navigation);
  const selected = operations.find((item) => item.operation_id === selectedId) ?? operations[0];

  useEffect(() => {
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !event.altKey) {
        event.preventDefault();
        document.getElementById('agent-search')?.focus();
      }
    };
    window.addEventListener('keydown', focusSearch);
    return () => window.removeEventListener('keydown', focusSearch);
  }, []);

  const request = useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const base = new URL(apiUrl);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
    if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash || (base.protocol === 'http:' && !loopback)) {
      throw new Error('Use HTTPS outside localhost and an API URL without credentials, query, or fragment.');
    }
    const method = (init?.method ?? 'GET').toUpperCase();
    const csrf = typeof document === 'undefined' ? '' : document.cookie.split('; ').find((item) => item.startsWith('sentinel_csrf='))?.split('=')[1] ?? '';
    const response = await fetch(`${apiUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      redirect: 'error',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(authMode === 'key' && apiKey ? { 'X-API-Key': apiKey } : {}), ...(authMode === 'member' && !['GET', 'HEAD', 'OPTIONS'].includes(method) && csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {}), ...(init?.headers ?? {}) },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: unknown };
      throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed with status ${response.status}`);
    }
    return response.json() as Promise<T>;
  }, [apiKey, apiUrl, authMode]);

  const loadOperations = useCallback(async () => {
    const data = await request<Operation[]>('/v1/operations?limit=100');
    setOperations(data);
    if (data.length && !data.some((item) => item.operation_id === selectedId)) setSelectedId(data[0].operation_id);
  }, [request, selectedId]);
  const loadEvents = useCallback(async (id: string) => {
    if (connected) setEvents(await request<OperationEvent[]>(`/v1/operations/${id}/events`));
  }, [connected, request]);
  function chooseOperation(id: string) {
    setSelectedId(id);
    loadEvents(id).catch((reason) => setError(reason.message));
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy('connect'); setError(null);
    try {
      if (authMode === 'member') {
        const values = new FormData(event.currentTarget);
        setApiKey('');
        const response = await fetch(`${apiUrl.replace(/\/$/, '')}/v1/sessions/login`, { method: 'POST', redirect: 'error', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ organization_slug: values.get('organization_slug'), handle: values.get('handle'), password: values.get('password') }) });
        if (!response.ok) throw new Error(response.status === 401 ? 'Organization, handle, or password is incorrect.' : `Login failed with status ${response.status}`);
      }
      await request('/v1/me');
      setOperations([]); setEvents([]); setConnected(true); setShowConnect(false);
      setNavigation('overview');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not connect to Sentinel.'); }
    finally { setBusy(null); }
  }
  async function runAction(action: 'approve' | 'reject' | 'revoke' | 'execute' | 'reconcile') {
    if (!selected || !connected) return;
    setBusy(action); setError(null);
    try {
      await request(`/v1/operations/${selected.operation_id}/${action}`, { method: 'POST', body: action === 'approve' ? JSON.stringify({ valid_for_seconds: 300 }) : undefined });
      await loadOperations(); await loadEvents(selected.operation_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The action could not be completed.'); }
    finally { setBusy(null); }
  }
  async function createOperation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!connected) return;
    const values = new FormData(event.currentTarget); setBusy('create'); setError(null);
    try {
      const operation = await request<Operation>('/v1/operations', { method: 'POST', body: JSON.stringify({ idempotency_key: `dashboard-${crypto.randomUUID()}`, action_type: 'book_viewing', action: { customer: values.get('customer'), slot: values.get('slot') } }) });
      await loadOperations(); chooseOperation(operation.operation_id); setShowCreate(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The operation could not be created.'); }
    finally { setBusy(null); }
  }

  const counts = useMemo(() => ({
    attention: operations.filter((item) => ['needs_review', 'unknown', 'failed'].includes(item.status)).length,
    pending: operations.filter((item) => item.status === 'awaiting_approval').length,
    active: operations.filter((item) => ['authorized', 'executing'].includes(item.status)).length,
    complete: operations.filter((item) => item.status === 'succeeded').length,
  }), [operations]);
  const visibleOperations = useMemo(() => operations.filter((item) => {
    const statusMatch = filter === 'all' || (filter === 'attention' && ['needs_review', 'unknown', 'failed'].includes(item.status)) || (filter === 'pending' && item.status === 'awaiting_approval') || (filter === 'active' && ['authorized', 'executing'].includes(item.status)) || (filter === 'complete' && item.status === 'succeeded');
    return statusMatch && `${item.action.customer} ${item.action.slot} ${item.operation_id}`.toLowerCase().includes(query.toLowerCase());
  }), [filter, operations, query]);

  function navigate(section: string, target: string, nextFilter?: typeof filter) {
    setNavigation(section);
    setSidebarOpen(false);
    if (nextFilter) setFilter(nextFilter);
    if (nextFilter === 'pending') {
      const pending = operations.find((operation) => operation.status === 'awaiting_approval');
      if (pending) chooseOperation(pending.operation_id);
    }
    if (['examples', 'operations', 'approvals', 'leads', 'calendar', 'engagement'].includes(section) && connected) {
      loadOperations().catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load reference operations.'));
    }
    requestAnimationFrame(() => document.getElementById(target)?.scrollIntoView({ block: 'start' }));
  }

  return <div className="app-shell cinematic-shell">
    <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <div className="brand"><div className="brand-mark"><ShieldCheck size={19} strokeWidth={2.2} /></div><div><strong>Sentinel</strong><span>Agent operations</span></div><button className="icon-button mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"><X size={18} /></button></div>
      <nav className="primary-nav" aria-label="Primary navigation">
        <span className="nav-label">Control room</span>
        <button className={`nav-item ${navigation === 'overview' ? 'active' : ''}`} onClick={() => navigate('overview', 'agent-workspace')}><LayoutDashboard size={17} />Agents and runs</button>
        <button className={`nav-item ${navigation === 'evidence' ? 'active' : ''}`} onClick={() => navigate('evidence', 'platform-evidence')}><Activity size={17} />Runs and evaluations</button>
        <span className="nav-label nav-label-spaced">Example integrations</span>
        <button className={`nav-item ${navigation === 'examples' ? 'active' : ''}`} onClick={() => navigate('examples', 'estateflow-example')}><Database size={17} />EstateFlow sandbox</button>
        <button className={`nav-item ${navigation === 'operations' ? 'active' : ''}`} onClick={() => navigate('operations', 'operation-queue', 'all')}><TerminalSquare size={17} />Operations<span className="nav-count">{operations.length}</span></button>
        <button className={`nav-item ${navigation === 'approvals' ? 'active' : ''}`} onClick={() => navigate('approvals', 'operation-queue', 'pending')}><ShieldCheck size={17} />Approvals<span className="nav-count warning">{counts.pending}</span></button>
        <button className={`nav-item ${navigation === 'leads' ? 'active' : ''}`} onClick={() => navigate('leads', 'lead-intake')}><Database size={17} />Leads</button>
        <button className={`nav-item ${navigation === 'calendar' ? 'active' : ''}`} onClick={() => navigate('calendar', 'viewing-calendar')}><CalendarDays size={17} />Viewing calendar</button>
        <button className={`nav-item ${navigation === 'engagement' ? 'active' : ''}`} onClick={() => navigate('engagement', 'engagement-queue')}><ArrowRight size={17} />Follow-up review</button>
        <span className="nav-label nav-label-spaced">Infrastructure</span>
        <button className={`nav-item ${navigation === 'control' ? 'active' : ''}`} onClick={() => navigate('control', 'control-center')}><SlidersHorizontal size={17} />Control center</button><button className={`nav-item ${navigation === 'health' ? 'active' : ''}`} onClick={() => navigate('health', 'operations-overview')}><Activity size={17} />Operations pulse</button><button className={`nav-item ${navigation === 'access' ? 'active' : ''}`} onClick={() => navigate('access', 'access-administration')}><KeyRound size={17} />Access</button>
      </nav>
      <div className="sidebar-status"><div className="status-head"><span className={`pulse ${connected ? 'online' : ''}`} /><strong>{connected ? 'API connected' : 'Not connected'}</strong></div><p>{connected ? apiUrl : 'Connect your agent workspace.'}</p><button onClick={() => { setConnected(false); setOperations([]); setEvents([]); setShowConnect(true); }}>{connected ? 'Change connection' : 'Connect API'}<ArrowRight size={14} /></button></div>
    </aside>
    {sidebarOpen && <button className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}

    <main className="main-content" id="overview">
      <header className="topbar"><button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Menu size={19} /></button><div className="workspace-switcher"><span className="workspace-avatar">AS</span><div><span>Workspace</span><strong>AgentOps Sentinel</strong></div><ChevronRight size={15} /></div><div className="topbar-actions"><button className="command-search" onClick={() => navigate('overview', 'agent-workspace')}><Search size={16} /><span>Find agents and runs</span><kbd><Command size={11} /> K</kbd></button><div className="environment"><span />{connected ? 'Live API' : 'Local'}</div></div></header>
      <div className="content-wrap">
        <section className="page-heading"><div><p className="eyebrow">AI AGENT TESTING &amp; OPERATIONS</p><h1>Evidence for every agent.</h1><p>Register your agents, inspect runs, evaluate outcomes, and govern sensitive actions across domains.</p></div><button className="primary-button" onClick={() => connected ? navigate('overview', 'agent-workspace') : setShowConnect(true)}><Plus size={16} />Connect an agent</button></section>
        {!connected && <section className="demo-banner"><div><CircleDot size={17} /><p><strong>Your agent workspace is ready.</strong> Connect Sentinel to load agents and runs. Fictional EstateFlow activity is available separately in Example integrations.</p></div><button onClick={() => setShowConnect(true)}>Connect API<ArrowRight size={14} /></button></section>}
        {error && <div className="error-banner" role="alert"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => setError(null)} aria-label="Dismiss error"><X size={15} /></button></div>}
        <AgentWorkspace connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <PlatformEvidence connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <AccessAdministration connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <OperationsOverview connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <ControlCenter connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        {showExamples && <div id="estateflow-example">
          <section className="demo-banner"><div><CircleDot size={17} /><p><strong>EstateFlow example integration.</strong> These lead, calendar and reference-booking screens exercise Sentinel. They are not requirements for connecting your own agent.</p></div><button onClick={() => connected ? setShowCreate(true) : setShowConnect(true)}>New reference operation<Plus size={14} /></button></section>
        <section className="metric-grid" aria-label="Operation summary">
          <button className={`metric-card danger ${filter === 'attention' ? 'selected' : ''}`} onClick={() => setFilter('attention')}><div className="metric-icon"><AlertTriangle size={18} /></div><div><span>Needs attention</span><strong>{counts.attention}</strong><small>Unknown or failed outcomes</small></div><ChevronRight size={17} className="metric-arrow" /></button>
          <button className={`metric-card amber ${filter === 'pending' ? 'selected' : ''}`} onClick={() => setFilter('pending')}><div className="metric-icon"><Clock3 size={18} /></div><div><span>Awaiting approval</span><strong>{counts.pending}</strong><small>Human decision required</small></div><ChevronRight size={17} className="metric-arrow" /></button>
          <button className={`metric-card cyan ${filter === 'active' ? 'selected' : ''}`} onClick={() => setFilter('active')}><div className="metric-icon"><Activity size={18} /></div><div><span>Active now</span><strong>{counts.active}</strong><small>Authorized or executing</small></div><ChevronRight size={17} className="metric-arrow" /></button>
          <button className={`metric-card green ${filter === 'complete' ? 'selected' : ''}`} onClick={() => setFilter('complete')}><div className="metric-icon"><CheckCircle2 size={18} /></div><div><span>Succeeded</span><strong>{counts.complete}</strong><small>Confirmed external results</small></div><ChevronRight size={17} className="metric-arrow" /></button>
        </section>
        <LeadIntakePanel connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <ViewingCalendar connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <EngagementQueue connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <PropertySearchPanel connected={connected} onConnect={() => setShowConnect(true)} request={request} />
        <section className="workspace-grid" id="operation-queue">
          <div className="operations-panel panel"><div className="panel-header"><div><h2>Operation queue</h2><p>{visibleOperations.length} of {operations.length} operations</p></div><button className="text-button" onClick={() => setFilter(filter === 'all' ? 'attention' : 'all')}><ListFilter size={15} />{filter === 'all' ? 'Attention only' : 'Clear filter'}</button></div><div className="table-tools"><label className="search-field"><Search size={15} /><input id="operation-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search customer, slot, or ID" /></label><button className="icon-button" title="Use summary cards to filter" aria-label="Filter operations"><SlidersHorizontal size={16} /></button></div>
            <div className="operation-list">{visibleOperations.map((operation) => <button key={operation.operation_id} className={`operation-row ${selected?.operation_id === operation.operation_id ? 'selected' : ''}`} onClick={() => chooseOperation(operation.operation_id)}><span className="operation-glyph"><Database size={16} /></span><span className="operation-main"><span className="operation-title">Book viewing · {operation.action.customer}</span><span className="operation-subtitle"><span className="mono">OP-{shortId(operation.operation_id)}</span><span>•</span><span>{operation.action.slot}</span></span></span><StatusBadge status={operation.status} /><span className="operation-time">{relativeTime(operation.updated_at)}</span><ChevronRight size={16} className="row-chevron" /></button>)}{visibleOperations.length === 0 && <div className="empty-state"><Search size={20} /><strong>No matching operations</strong><span>Try another search or clear the current filter.</span></div>}</div>
          </div>
          <aside className="detail-panel panel">{selected ? <>
            <div className="detail-head"><div><span className="mono detail-id">OP-{shortId(selected.operation_id)}</span><h2>{selected.action.customer}</h2><p>Book viewing · {selected.action.slot}</p></div><StatusBadge status={selected.status} /></div>
            {['needs_review', 'unknown'].includes(selected.status) && <div className="risk-callout"><AlertTriangle size={17} /><div><strong>Human review required</strong><p>{selected.last_error ?? 'The external outcome could not be confirmed safely.'}</p></div></div>}
            <div className="action-bar">{selected.status === 'awaiting_approval' && <><button className="primary-button compact" disabled={!connected || !!busy} onClick={() => runAction('approve')}><Check size={15} />Approve</button><button className="secondary-button compact" disabled={!connected || !!busy} onClick={() => runAction('reject')}><X size={15} />Reject</button></>}{selected.status === 'authorized' && <><button className="primary-button compact" disabled={!connected || !!busy} onClick={() => runAction('execute')}><Play size={15} />Execute</button><button className="secondary-button compact" disabled={!connected || !!busy} onClick={() => runAction('revoke')}><LockKeyhole size={15} />Revoke</button></>}{['needs_review', 'unknown'].includes(selected.status) && <button className="primary-button compact" disabled={!connected || !!busy} onClick={() => runAction('reconcile')}><RefreshCw size={15} />Reconcile outcome</button>}{!connected && <span className="action-hint">Connect the API to take action</span>}</div>
            <div className="detail-section"><div className="section-title"><h3>Requested action</h3><span>Exact payload</span></div><div className="payload"><div><span>action_type</span><code>{selected.action_type}</code></div><div><span>customer</span><code>{selected.action.customer}</code></div><div><span>slot</span><code>{selected.action.slot}</code></div>{selected.external_id && <div><span>external_id</span><code>{selected.external_id}</code></div>}</div></div>
            <div className="detail-section timeline-section"><div className="section-title"><h3>Evidence timeline</h3><span>{events.length} events</span></div><div className="timeline">{events.map((item, index) => <div className="timeline-item" key={item.event_id}><span className={`timeline-node ${index === events.length - 1 ? 'current' : ''}`} /><div><strong>{item.event_type.replaceAll('.', ' ')}</strong><span>{item.from_status ? `${statusMeta[item.from_status as OperationStatus]?.label ?? item.from_status} → ` : ''}{statusMeta[item.to_status as OperationStatus]?.label ?? item.to_status}</span><time>{new Date(item.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</time></div></div>)}</div></div>
          </> : <div className="empty-state"><TerminalSquare size={22} /><strong>Select an operation</strong><span>Its action, status, and evidence will appear here.</span></div>}</aside>
        </section>
        </div>}
      </div>
    </main>

    {showConnect && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setShowConnect(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="connect-title"><div className="modal-head"><div><span className="modal-icon"><Server size={19} /></span><div><h2 id="connect-title">Connect Sentinel API</h2><p>Use a service key or a browser member account.</p></div></div><button className="icon-button" onClick={() => setShowConnect(false)} aria-label="Close"><X size={18} /></button></div><form onSubmit={connect}><label>API URL<input type="url" value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} required /></label><label>Authentication<select value={authMode} onChange={(event) => setAuthMode(event.target.value as 'key' | 'member')}><option value="key">Service API key</option><option value="member">Member login</option></select></label>{authMode === 'key' ? <label>API key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="snt_..." required autoComplete="off" /></label> : <><label>Organization slug<input name="organization_slug" required pattern="[a-z][a-z0-9-]{2,49}" autoComplete="organization" /></label><label>Member handle<input name="handle" required autoComplete="username" /></label><label>Password<input name="password" type="password" required autoComplete="current-password" /></label></>}<div className="security-note"><LockKeyhole size={15} /><span>{authMode === 'key' ? 'The key stays in this browser tab and is never stored.' : 'The server creates an HTTP-only session; writes require its CSRF token.'}</span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowConnect(false)}>Cancel</button><button className="primary-button" disabled={busy === 'connect'}>{busy === 'connect' ? <RefreshCw size={16} className="spin" /> : <ArrowRight size={16} />}Connect workspace</button></div></form></section></div>}
    {showCreate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setShowCreate(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><div className="modal-head"><div><span className="modal-icon"><Plus size={19} /></span><div><h2 id="create-title">Create operation</h2><p>The action will enter the approval queue before execution.</p></div></div><button className="icon-button" onClick={() => setShowCreate(false)} aria-label="Close"><X size={18} /></button></div><form onSubmit={createOperation}><label>Customer<input name="customer" required maxLength={100} placeholder="e.g. Priya Shah" /></label><label>Viewing slot<input name="slot" required maxLength={100} placeholder="e.g. 14 Sep · 3:00 PM" /></label><div className="security-note"><ShieldCheck size={15} /><span>Sentinel will bind any approval to this exact action payload.</span></div><div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>Cancel</button><button className="primary-button" disabled={busy === 'create'}>{busy === 'create' ? <RefreshCw size={16} className="spin" /> : <Plus size={16} />}Create operation</button></div></form></section></div>}
  </div>;
}
