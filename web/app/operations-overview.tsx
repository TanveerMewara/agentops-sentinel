'use client';
import { useEffect, useState } from 'react';
import { Activity, Clock3, RefreshCw, ShieldCheck, AlertTriangle } from 'lucide-react';

type Overview = {
  captured_at: string;
  tool_calls: { awaiting_approval: number; ready: number; unknown: number; needs_review: number; expired_leases: number; completed: number };
  runs: Record<string, number>;
  access: { active_keys: number; expiring_keys: number; rate_limit_blocks: number };
  request_policy: { requests: number; window_seconds: number };
  installed_adapters: { name: string; version: string }[];
  booking_circuit?: { state: 'closed' | 'open' | 'probing'; retry_after_seconds: number; scope: 'api_process' } | null;
  boundary: string;
};
type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };

export default function OperationsOverview({ connected, onConnect, request }: Props) {
  const [snapshot, setSnapshot] = useState<{ request: Props['request']; data: Overview } | null>(null);
  const data = snapshot?.request === request ? snapshot.data : null;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (connected) request('/v1/operations/overview').then((value) => {
      if (active) { setSnapshot({ request, data: value as Overview }); setError(null); }
    }).catch(() => { if (active) { setSnapshot(null); setError('Operational counters require an admin, developer, or reviewer key. Check the API connection and role.'); } });
    return () => { active = false; };
  }, [connected, request]);

  async function refresh() {
    if (!connected) { onConnect(); return; }
    setBusy(true); setError(null);
    try { setSnapshot({ request, data: await request('/v1/operations/overview') as Overview }); }
    catch { setSnapshot(null); setError('Could not load counters. Check the API connection, role, and request limit.'); }
    finally { setBusy(false); }
  }

  const cards = data ? [
    { label: 'Waiting for review', value: data.tool_calls.awaiting_approval, hint: 'Exact-action approval required', icon: ShieldCheck },
    { label: 'Uncertain outcomes', value: data.tool_calls.unknown, hint: 'Reconcile before any further action', icon: AlertTriangle },
    { label: 'Expired execution leases', value: data.tool_calls.expired_leases, hint: 'Worker recovery may be needed', icon: Clock3 },
    { label: 'Completed tool calls', value: data.tool_calls.completed, hint: 'Results recorded in the ledger', icon: Activity },
  ] : [];

  return <section className="ops-overview" id="operations-overview" aria-labelledby="ops-overview-title">
    <div className="ops-overview-head"><div><div className="ops-overview-eyebrow"><Activity size={13} /> OPERATIONS PULSE</div>
      <h2 id="ops-overview-title">See what needs attention.</h2><p>Organization-scoped signals from your durable execution ledger.</p></div>
      <button className="secondary-button" onClick={refresh} disabled={busy}><RefreshCw size={14} /> {busy ? 'Refreshing…' : connected ? 'Refresh signals' : 'Connect API'}</button></div>
    <div role="status" className="ops-overview-message">{error || (!connected ? 'Connect your API to load live operational counters.' : !data ? 'Load operational counters with an authorized key.' : '')}</div>
    {connected && data && <>
      <div className="ops-overview-cards">{cards.map(({ label, value, hint, icon: Icon }) => <article key={label}>
        <div><span>{label}</span><Icon size={16} /></div><strong>{value.toLocaleString()}</strong><p>{hint}</p></article>)}</div>
      <div className={`ops-provider-guard ${data.booking_circuit?.state || 'unavailable'}`}>
        <div className="ops-provider-guard-heading"><ShieldCheck size={18} /><div><h3>Booking dispatch guard</h3>
          <p>Availability protection for this API process</p></div><span>{!data.booking_circuit ? 'Not reported' : data.booking_circuit.state === 'closed' ? 'Dispatch permitted' : data.booking_circuit.state === 'probing' ? 'Checking recovery' : 'Dispatch paused'}</span></div>
        <p>{!data.booking_circuit ? 'This deployment does not report a reference booking circuit. No provider health conclusion is available.' : data.booking_circuit.state === 'closed' ? 'The guard allows new authorized bookings. This is not a live provider health check or proof that a booking succeeded.' : data.booking_circuit.state === 'probing' ? 'One read-only health check is running. New booking writes remain paused; receipt recovery can continue.' : data.booking_circuit.retry_after_seconds > 0 ? `At capture, the next health probe was permitted in ${data.booking_circuit.retry_after_seconds}s. Receipt recovery remains available; uncertain bookings are never replayed.` : 'The cooldown has elapsed. The next dispatch attempt may run a read-only health probe; the guard remains paused until recovery is confirmed.'}</p>
        <small>Snapshot only. Refresh signals to update. Refresh does not probe the provider or dispatch a booking.</small>
      </div>
      <div className="ops-overview-detail"><div><h3>Access guardrails</h3><dl>
        <div><dt>Active service keys</dt><dd>{data.access.active_keys}</dd></div>
        <div><dt>Keys expiring within 7 days</dt><dd>{data.access.expiring_keys}</dd></div>
        <div><dt>Request-limit blocks, all time</dt><dd>{data.access.rate_limit_blocks}</dd></div>
        <div><dt>Per-key request policy</dt><dd>{data.request_policy.requests} / {data.request_policy.window_seconds}s</dd></div>
      </dl></div><div><h3>Installed adapter contracts</h3><div className="ops-overview-adapters">
        {data.installed_adapters.map((adapter) => <span key={`${adapter.name}-${adapter.version}`}>{adapter.name}<small>v{adapter.version}</small></span>)}
        {!data.installed_adapters.length && <p>No tool adapters are installed in this deployment.</p>}
      </div><p className="ops-overview-caption">Registration alone does not install executable adapter code.</p></div></div>
      <div className="ops-overview-foot"><span>{data.boundary}</span><time dateTime={data.captured_at}>Captured {new Date(data.captured_at).toLocaleString()}</time></div>
    </>}
  </section>;
}
