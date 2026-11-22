'use client';
import { useEffect, useState, type FormEvent } from 'react';

type Trace = {
  source: string; reported_status: string; duration_ms: number; content_hash: string;
  output?: Record<string, unknown>;
  spans: { span_id: string; parent_id: string | null; name: string; kind: string; status: string; duration_ms: number; start_offset_ms: number }[];
  usage: { reported_tokens: number; model_spans: number; spans_with_usage: number };
};

export default function ExternalTraceInspector({ runId, request, canWrite }: {
  runId: string; request: (path: string, init?: RequestInit) => Promise<unknown>; canWrite: boolean;
}) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    document.getElementById('external-trace-inspector')?.scrollIntoView({ block: 'start' });
    request(`/v1/runs/${runId}/external-trace`).then((data) => {
      if (active) setTrace(data as Trace);
    }).catch(() => {
      if (active) setNotice('No trace was loaded. This run may have no external trace, or the request failed.');
    }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [runId, request]);

  async function importTrace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setNotice('');
    try {
      const body = JSON.parse(payload);
      if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('Paste a JSON evidence object.');
      setTrace(await request(`/v1/runs/${runId}/external-trace`, { method: 'POST', body: JSON.stringify(body) }) as Trace);
      setNotice('Finalized evidence saved. Keep this exact JSON and key for replay.');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Trace import failed.'); }
    finally { setBusy(false); }
  }
  async function revealOutput() {
    setBusy(true); setError(null);
    try { setTrace(await request(`/v1/runs/${runId}/external-trace?include_output=true`) as Trace); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Output could not be loaded.'); }
    finally { setBusy(false); }
  }
  return <section id="external-trace-inspector" className="evidence-results external-trace-inspector" aria-label="External run evidence">
    <h3>External run evidence</h3><p className="evidence-note">Run: <code>{runId}</code></p>
    <p className="evidence-note">Caller-reported observations are not proof of Sentinel approval or execution. Import does not change run status, consume approvals, execute tools, or update governed token budgets.</p>
    {busy && <p role="status" className="evidence-note">Loading external evidence…</p>}
    {trace && <>
      <div className="evidence-metrics"><div><strong>{trace.reported_status.replaceAll('_', ' ')}</strong><span>Reported outcome</span></div><div><strong>{trace.duration_ms} ms</strong><span>Reported duration</span></div><div><strong>{trace.spans.length}</strong><span>Reported spans</span></div><div><strong>{trace.usage.reported_tokens}</strong><span>Known reported tokens</span></div></div>
      <p className="evidence-note">Source: {trace.source} · Trust: caller reported. Token counts supplied for {trace.usage.spans_with_usage}/{trace.usage.model_spans} reported model spans. Unreported activity is unknown; zero known tokens does not prove zero usage.</p>
      <p className="evidence-note">Content hash: <code>{trace.content_hash}</code></p>
      <ol className="external-span-list">{trace.spans.map((span) => <li key={span.span_id}><strong>{span.name}</strong><span>{span.kind} · {span.status.replaceAll('_', ' ')} · {span.duration_ms} ms · starts at {span.start_offset_ms} ms</span><small>ID: {span.span_id}{span.parent_id ? ` · parent: ${span.parent_id}` : ' · root'}</small></li>)}</ol>
      {trace.output === undefined ? <button type="button" className="secondary-button" disabled={busy} onClick={revealOutput}>Reveal submitted output</button> : <><p className="evidence-note">Submitted output is displayed as text; correctness has not been verified.</p><pre className="external-output">{JSON.stringify(trace.output, null, 2)}</pre></>}
    </>}
    {canWrite && <form onSubmit={importTrace}><label>Import finalized evidence JSON<textarea value={payload} onChange={(event) => setPayload(event.target.value)} disabled={busy} required placeholder="Paste JSON returned by TraceRecorder.finish(...)" /></label><p className="evidence-note">One immutable finalized trace per external run; maximum 100 spans and 64 KiB. Remove private data and credentials before submission. Replay requires the same key and exact evidence.</p><button className="secondary-button" disabled={busy || !payload.trim()}>Save external evidence</button></form>}
    {notice && <p className="evidence-note" role="status">{notice}</p>}{error && <p className="property-error" role="alert">{error}</p>}
  </section>;
}
