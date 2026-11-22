'use client';

import { type FormEvent, useEffect, useState } from 'react';
import { Activity, FlaskConical, RefreshCw, Download, CheckCircle2, AlertTriangle } from 'lucide-react';

type Run = { run_id: string; status: string; agent_version_id: string };
type Dataset = { dataset_id: string; slug: string; version: number; definition: { cases: { case_key: string; expected: Record<string, unknown> }[] } };
type Report = { experiment_id: string; dataset_id: string; dataset_slug: string; dataset_version: number; pass_rate: number; passed_cases: number; total_cases: number; gate: { passed: boolean }; cases: { case_key: string; passed: boolean; checks: { rule: string; passed: boolean; expected: unknown; actual: unknown }[] }[] };
type Trace = { run: Run; metrics: { model_tokens: number; model_duration_ms: number; model_calls: number; run_duration_ms: number | null }; timeline: { id: string; source: string; kind: string; at: string; tokens?: number; duration_ms?: number }[] };
type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };

export default function PlatformEvidence(props: Props) {
  const [session, setSession] = useState({ request: props.request, connected: props.connected, generation: 0 });
  if (session.request !== props.request || session.connected !== props.connected) {
    setSession({ request: props.request, connected: props.connected, generation: session.generation + 1 });
  }
  return <EvidenceSession key={session.generation} {...props} />;
}

function EvidenceSession({ connected, onConnect, request }: Props) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [experimentKey, setExperimentKey] = useState('');
  const [trace, setTrace] = useState<Trace | null>(null);
  const [selectedRun, setSelectedRun] = useState('');
  const [activeReport, setActiveReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slug, setSlug] = useState('agent-regression');
  const [version, setVersion] = useState(1);
  const [expectedStatus, setExpectedStatus] = useState('succeeded');
  const [expectProperty, setExpectProperty] = useState(false);
  const [additionalExpectations, setAdditionalExpectations] = useState('{}');
  const [referenceOutput, setReferenceOutput] = useState('');
  const [outputSchema, setOutputSchema] = useState('');
  const [comparison, setComparison] = useState<number | null>(null);
  const [left, setLeft] = useState('');
  const [right, setRight] = useState('');
  const dataset = datasets.find((item) => item.dataset_id === datasetId);

  async function fetchData() {
    const [runData, datasetData, reportData] = await Promise.all([
      request('/v1/runs?limit=100'), request('/v1/evaluations/datasets?limit=100'),
      request('/v1/evaluations/experiments?limit=50'),
    ]);
    return { runs: runData as Run[], datasets: datasetData as Dataset[], reports: reportData as Report[] };
  }

  useEffect(() => {
    let active = true;
    if (connected) Promise.all([request('/v1/runs?limit=100'), request('/v1/evaluations/datasets?limit=100'), request('/v1/evaluations/experiments?limit=50')])
      .then(([runData, datasetData, reportData]) => { if (active) { setRuns(runData as Run[]); setDatasets(datasetData as Dataset[]); setReports(reportData as Report[]); } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load evidence.'); });
    return () => { active = false; };
  }, [connected, request]);

  async function refresh() {
    if (!connected) { onConnect(); return; }
    setBusy(true); setError(null);
    try { const data = await fetchData(); setRuns(data.runs); setDatasets(data.datasets); setReports(data.reports); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not refresh.'); }
    finally { setBusy(false); }
  }

  async function createDataset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const extra: unknown = JSON.parse(additionalExpectations);
      if (!extra || typeof extra !== 'object' || Array.isArray(extra)) throw new Error('Additional expectations must be a JSON object.');
      const outputRules: Record<string, unknown> = {};
      for (const [name, text] of [['output_equals', referenceOutput], ['output_schema', outputSchema]]) {
        if (!text.trim()) continue;
        let value: unknown;
        try { value = JSON.parse(text); } catch { throw new Error('Output requirements must be valid JSON.'); }
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Output requirements must be JSON objects.');
        outputRules[name] = value;
      }
      const result = await request('/v1/evaluations/datasets', { method: 'POST', body: JSON.stringify({ slug, version,
        cases: [{ case_key: 'agent-outcome', expected: { ...extra, ...outputRules, run_status: expectedStatus,
          ...(expectProperty ? { property_bound: true, completed_bookings: 1, approvals_consumed: true } : {}) } }] }) }) as Dataset;
      setDatasets(await request('/v1/evaluations/datasets?limit=100') as Dataset[]);
      setDatasetId(result.dataset_id); setBindings({}); setExperimentKey(`evaluation-${crypto.randomUUID()}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not create dataset.'); }
    finally { setBusy(false); }
  }

  async function evaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const result = await request('/v1/evaluations/experiments', { method: 'POST', body: JSON.stringify({
        idempotency_key: experimentKey, dataset_id: datasetId, bindings, min_pass_rate: 1 }) }) as Report;
      setActiveReport(result); setExperimentKey(`evaluation-${crypto.randomUUID()}`);
      setReports(await request('/v1/evaluations/experiments?limit=50') as Report[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not evaluate.'); }
    finally { setBusy(false); }
  }

  async function loadTrace(value: string) {
    setSelectedRun(value); setTrace(null);
    if (!value) return;
    setBusy(true); setError(null);
    try { setTrace(await request(`/v1/runs/${value}/timeline`) as Trace); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load timeline.'); }
    finally { setBusy(false); }
  }

  async function compare() {
    setBusy(true); setError(null); setComparison(null);
    try { const result = await request(`/v1/evaluations/compare?left=${left}&right=${right}`) as { pass_rate_delta: number }; setComparison(result.pass_rate_delta); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not compare.'); }
    finally { setBusy(false); }
  }

  function exportReport(report: Report) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `sentinel-evaluation-${report.experiment_id}.json`; anchor.click(); URL.revokeObjectURL(url);
  }

  return <section className="platform-evidence panel" id="platform-evidence" aria-labelledby="evidence-heading">
    <div className="evidence-head"><FlaskConical size={23} /><div><p className="property-eyebrow">AGENT QUALITY</p><h2 id="evidence-heading">Evaluation and execution evidence</h2><p>Check saved runs against versioned expectations. No agent actions are executed.</p></div><button className="secondary-button compact" onClick={refresh} disabled={busy}><RefreshCw size={14} />Refresh</button></div>
    {!connected ? <button className="engagement-connect" onClick={onConnect}>Connect the API to evaluate runs</button> : <>
      <div className="evidence-grid"><form onSubmit={createDataset}><h3>Create a regression case</h3><label>Dataset name<input required pattern="[a-z][a-z0-9_-]{2,79}" value={slug} onChange={(event) => setSlug(event.target.value)} /></label><div className="evidence-inline"><label>Version<input required type="number" min={1} max={1000000} value={version} onChange={(event) => setVersion(Number(event.target.value))} /></label><label>Expected result<select value={expectedStatus} onChange={(event) => setExpectedStatus(event.target.value)}>{['succeeded', 'failed', 'cancelled', 'needs_review'].map((value) => <option key={value}>{value}</option>)}</select></label></div><label>Additional expectations (JSON)<textarea value={additionalExpectations} onChange={(event) => setAdditionalExpectations(event.target.value)} placeholder={'{"max_steps_used":12,"max_model_tokens":2000,"max_model_duration_ms":5000}'} /></label><p className="evidence-note">Optional general limits: max_steps_used, max_model_tokens and max_model_duration_ms. Unknown rules are rejected by the API.</p><details className="output-requirements"><summary>Check submitted output</summary><label>Exact expected output (optional JSON)<textarea value={referenceOutput} onChange={(event) => setReferenceOutput(event.target.value)} placeholder={'{"category":"billing","priority":"normal"}'} /></label><label>Output schema (optional JSON)<textarea value={outputSchema} onChange={(event) => setOutputSchema(event.target.value)} placeholder={'{"type":"object","required":["answer"],"properties":{"answer":{"type":"string","minLength":1}}}'} /></label><p className="evidence-note">Leave blank to skip a check. Exact checks preserve string values and array order; numeric values compare equally, while booleans remain distinct. Schemas support types, properties, required fields, enums and size/numeric limits. References, regex and schema combinations are unsupported. Maximum 16 KiB per rule. Missing external output fails the check; use a new dataset version when requirements change.</p></details><label className="evidence-checkbox"><input type="checkbox" checked={expectProperty} onChange={(event) => setExpectProperty(event.target.checked)} />EstateFlow-specific check: one property-bound reference booking with approvals consumed</label><button className="secondary-button" disabled={busy}>Save immutable version</button></form>
      <form onSubmit={evaluate}><h3>Run the release checks</h3><label>Dataset<select required value={datasetId} disabled={busy} onChange={(event) => { setDatasetId(event.target.value); setBindings({}); setExperimentKey(`evaluation-${crypto.randomUUID()}`); }}>{<option value="">Choose a dataset</option>}{datasets.map((item) => <option key={item.dataset_id} value={item.dataset_id}>{item.slug} · v{item.version}</option>)}</select></label>{dataset?.definition.cases.map((item) => <label key={item.case_key}>{item.case_key}<select required value={bindings[item.case_key] ?? ''} disabled={busy} onChange={(event) => { setBindings({ ...bindings, [item.case_key]: event.target.value }); setExperimentKey(`evaluation-${crypto.randomUUID()}`); }}><option value="">Choose a completed run</option>{runs.filter((run) => !['queued', 'running'].includes(run.status)).map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8).toUpperCase()} · {run.status}</option>)}</select></label>)}<p className="evidence-note">Every case must pass this gate. Saved facts stay frozen if later drafts change.</p><button className="primary-button" disabled={busy || !dataset}>Evaluate saved runs</button></form></div>
      <div className="evidence-results"><p className="evidence-note">Output checks validate submitted JSON against configured requirements. They do not establish semantic truth, safety or authorized execution; exports omit raw output and reference/schema values.</p><div className="evidence-inline"><h3>Experiment reports</h3><select aria-label="Open experiment report" value={activeReport?.experiment_id ?? ''} onChange={(event) => setActiveReport(reports.find((report) => report.experiment_id === event.target.value) ?? null)}><option value="">Choose a report</option>{reports.map((report) => <option key={report.experiment_id} value={report.experiment_id}>{report.dataset_slug} v{report.dataset_version} · {Math.round(report.pass_rate * 100)}% · {report.experiment_id.slice(0, 8)}</option>)}</select></div>{activeReport && <><div className={`evidence-gate ${activeReport.gate.passed ? 'passed' : 'failed'}`}>{activeReport.gate.passed ? <CheckCircle2 size={20} /> : <AlertTriangle size={20} />}<strong>{activeReport.gate.passed ? 'Gate passed' : 'Gate failed'}</strong><span>{activeReport.passed_cases}/{activeReport.total_cases} cases passed</span><button className="secondary-button compact" onClick={() => exportReport(activeReport)}><Download size={13} />Export JSON</button></div>{activeReport.cases.map((item) => <div className="evidence-case" key={item.case_key}><strong>{item.case_key}</strong>{item.checks.map((check) => <p key={check.rule}><span className={check.passed ? 'evidence-pass' : 'evidence-fail'}>{check.passed ? 'PASS' : 'FAIL'}</span>{check.rule.replaceAll('_', ' ')}<code>expected {JSON.stringify(check.expected)} · actual {JSON.stringify(check.actual)}</code></p>)}</div>)}</>}
      <div className="evidence-inline"><label>Baseline<select value={left} onChange={(event) => { setLeft(event.target.value); setComparison(null); }}><option value="">Choose report</option>{reports.map((report) => <option key={report.experiment_id} value={report.experiment_id}>{report.experiment_id.slice(0, 8)} · {report.dataset_slug}</option>)}</select></label><label>Candidate<select value={right} onChange={(event) => { setRight(event.target.value); setComparison(null); }}><option value="">Choose report</option>{reports.map((report) => <option key={report.experiment_id} value={report.experiment_id}>{report.experiment_id.slice(0, 8)} · {report.dataset_slug}</option>)}</select></label><button className="secondary-button" disabled={busy || !left || !right} onClick={compare}>Compare</button></div>{comparison !== null && <p className="evidence-note">Candidate pass-rate change: {comparison >= 0 ? '+' : ''}{(comparison * 100).toFixed(1)} percentage points. Compared on the same dataset version.</p>}</div>
      <div className="evidence-results"><h3><Activity size={16} />Run timeline</h3><label>Run<select value={selectedRun} disabled={busy} onChange={(event) => loadTrace(event.target.value)}><option value="">Choose a run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id.slice(0, 8).toUpperCase()} · {run.status}</option>)}</select></label>{trace && <><div className="evidence-metrics"><div><strong>{trace.metrics.model_tokens}</strong><span>Governed model tokens</span></div><div><strong>{trace.metrics.model_duration_ms} ms</strong><span>Governed model duration</span></div><div><strong>{trace.metrics.model_calls}</strong><span>Governed model calls</span></div><div><strong>{trace.metrics.run_duration_ms === null ? '—' : `${trace.metrics.run_duration_ms} ms`}</strong><span>Run duration</span></div></div><ol className="evidence-timeline">{trace.timeline.map((entry) => <li key={`${entry.source}-${entry.id}`}><span>{entry.source}</span><strong>{entry.kind}</strong><time dateTime={entry.at}>{new Date(entry.at).toLocaleString()}</time>{entry.tokens !== undefined && <small>{entry.tokens} tokens · {entry.duration_ms} ms</small>}</li>)}</ol><p className="evidence-note">Contact details, prompts, arguments, outputs, and event payloads are omitted. This timeline uses the event ledger. OpenTelemetry export and priced cost estimates remain unavailable.</p></>}</div>
    </>}{error && <p className="property-error" role="alert">{error}</p>}
  </section>;
}
