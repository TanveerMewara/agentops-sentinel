'use client';

import { ArrowRight, CheckCircle2, CircleHelp, HandHeart, Mail, RefreshCw, Users } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';

type LeadStatus = 'needs_information' | 'qualified' | 'nurture' | 'human_review';
type Lead = {
  lead_id: string; external_key: string; customer_name: string; contact_email: string | null;
  city: string | null; max_budget_inr: string | null; min_bedrooms: number | null;
  timeline: string; outreach_consent: boolean; qualification_status: LeadStatus;
  qualification_reasons: string[]; current_version: number; updated_at: string;
};
type Props = {
  connected: boolean; onConnect: () => void;
  request: (path: string, init?: RequestInit) => Promise<unknown>;
};
type CalendarSlot = {
  slot_id: string; property_id: string; property_version: number;
  starts_at: string; ends_at: string; available: boolean; property_title: string;
};

const statusText: Record<LeadStatus, string> = {
  needs_information: 'Needs information', qualified: 'Ready for viewing',
  nurture: 'Later timeline', human_review: 'Human review',
};
const reasonText: Record<string, string> = {
  outreach_consent_missing: 'Outreach consent missing',
  contact_email_missing: 'Contact email missing', city_missing: 'City missing',
  budget_missing: 'Budget missing', timeline_missing: 'Timeline missing',
  timeline_later: 'Searching later', person_requested: 'Asked for a person',
  requirements_complete: 'Requirements complete', manual_handoff: 'Routed to a person',
};

export default function LeadIntakePanel({ connected, onConnect, request }: Props) {
  const [connection, setConnection] = useState({ connected, request, generation: 0 });
  if (connection.connected !== connected || connection.request !== request) {
    setConnection({ connected, request, generation: connection.generation + 1 });
  }
  return <LeadIntakeSession key={connection.generation} connected={connected} onConnect={onConnect} request={request} />;
}

function LeadIntakeSession({ connected, onConnect, request }: Props) {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [externalKey, setExternalKey] = useState('');
  const [customerName, setCustomerName] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [city, setCity] = useState('');
  const [budget, setBudget] = useState('');
  const [bedrooms, setBedrooms] = useState('');
  const [timeline, setTimeline] = useState('unknown');
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [launchLead, setLaunchLead] = useState<Lead | null>(null);
  const [agents, setAgents] = useState<{ agent_id: string; display_name: string }[]>([]);
  const [versions, setVersions] = useState<{ agent_version_id: string; version: string }[]>([]);
  const [agentId, setAgentId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [viewingSlot, setViewingSlot] = useState('');
  const [launchKey, setLaunchKey] = useState('');
  const [scheduling, setScheduling] = useState<'native' | 'reference'>('native');
  const [calendarSlots, setCalendarSlots] = useState<CalendarSlot[]>([]);
  const [nativeSlotId, setNativeSlotId] = useState('');
  const [nativeVersionId, setNativeVersionId] = useState('');

  useEffect(() => {
    let active = true;
    if (connected) request('/v1/leads?limit=50').then((value) => {
      if (active) setLeads(value as Lead[]);
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Could not load leads.');
    });
    return () => { active = false; };
  }, [connected, request]);

  async function refresh() {
    if (!connected) { onConnect(); return; }
    setLoading(true); setError(null);
    try { setLeads(await request('/v1/leads?limit=50') as Lead[]); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load leads.'); }
    finally { setLoading(false); }
  }

  async function chooseViewing(lead: Lead) {
    setLoading(true); setError(null);
    try {
      const [loadedAgents, slots] = await Promise.all([
        request('/v1/agents'), request('/v1/calendar/slots?limit=100'),
      ]);
      setAgents(loadedAgents as { agent_id: string; display_name: string }[]);
      setCalendarSlots((slots as CalendarSlot[]).filter((slot) => slot.available));
      setLaunchLead(lead); setAgentId(''); setVersionId(''); setVersions([]);
      setScheduling('native'); setNativeSlotId(''); setNativeVersionId('');
      setViewingSlot(''); setLaunchKey(`lead-viewing-${crypto.randomUUID()}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load agents.'); }
    finally { setLoading(false); }
  }

  async function enableNativeAgent() {
    setLoading(true); setError(null);
    try {
      const configured = await request('/v1/calendar/workflow/configuration', {
        method: 'POST', body: '{}',
      }) as { agent_version_id: string };
      setNativeVersionId(configured.agent_version_id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not enable the native viewing agent.'); }
    finally { setLoading(false); }
  }

  async function chooseAgent(value: string) {
    setAgentId(value); setVersionId(''); setVersions([]); setLoading(true); setError(null);
    setLaunchKey(`lead-viewing-${crypto.randomUUID()}`);
    try {
      if (value) setVersions(await request(`/v1/agents/${value}/versions`) as { agent_version_id: string; version: string }[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load agent versions.'); }
    finally { setLoading(false); }
  }

  async function launchViewing(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!launchLead) return;
    setLoading(true); setError(null); setNotice(null);
    try {
      const run = await request(`/v1/leads/${launchLead.lead_id}/runs`, {
        method: 'POST', body: JSON.stringify({ idempotency_key: launchKey,
          agent_version_id: scheduling === 'native' ? nativeVersionId : versionId,
          ...(scheduling === 'native' ? { native_slot_id: nativeSlotId }
            : { slot: new Date(viewingSlot).toISOString() }) }),
      }) as { run_id: string; status: string };
      setNotice(`Viewing run ${run.run_id.slice(0, 8).toUpperCase()} queued. Start the automatic worker or use Runs to plan it; exact approval is required before reservation.`);
      setLaunchLead(null);
    } catch (reason) { setError(`${reason instanceof Error ? reason.message : 'Could not confirm viewing run.'} Keep this form to retry the same request; inspect Runs before starting a new request.`); }
    finally { setLoading(false); }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!connected) { onConnect(); return; }
    setLoading(true); setError(null); setNotice(null);
    try {
      const body: Record<string, unknown> = {
        external_key: externalKey.trim(), customer_name: customerName.trim(),
        channel: 'manual', contact_email: contactEmail.trim() || null,
        city: city.trim() || null, max_budget_inr: budget || null,
        min_bedrooms: bedrooms ? Number(bedrooms) : null,
        timeline, outreach_consent: consent,
      };
      const result = await request('/v1/leads', {
        method: 'POST', body: JSON.stringify(body),
      }) as { lead: Lead; outcome: string };
      setNotice(`${result.lead.customer_name}: ${statusText[result.lead.qualification_status]}.`);
      setLeads(await request('/v1/leads?limit=50') as Lead[]);
      if (result.outcome === 'created') {
        setExternalKey(''); setCustomerName(''); setContactEmail('');
        setCity(''); setBudget(''); setBedrooms(''); setTimeline('unknown'); setConsent(false);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save lead.'); }
    finally { setLoading(false); }
  }

  async function routeToPerson(lead: Lead) {
    setLoading(true); setError(null); setNotice(null);
    try {
      await request(`/v1/leads/${lead.lead_id}/handoff`, {
        method: 'POST', body: JSON.stringify({ reason_code: 'agent_uncertain' }),
      });
      setLeads(await request('/v1/leads?limit=50') as Lead[]);
      setNotice(`${lead.customer_name} is in the human review queue.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not route lead.'); }
    finally { setLoading(false); }
  }

  async function finishReview(lead: Lead) {
    setLoading(true); setError(null); setNotice(null);
    try {
      const outcome = await request(`/v1/leads/${lead.lead_id}/resolve-review`, {
        method: 'POST', body: JSON.stringify({ resolution_code: 'answered_questions' }),
      }) as Lead;
      setLeads(await request('/v1/leads?limit=50') as Lead[]);
      setNotice(`${lead.customer_name}: ${statusText[outcome.qualification_status]}.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not finish review. A reviewer key is required.'); }
    finally { setLoading(false); }
  }

  return <section className="lead-intake panel" id="lead-intake" aria-labelledby="lead-heading">
    <div className="lead-intake-head">
      <div className="lead-intake-icon"><Users size={20} /></div>
      <div><p className="property-eyebrow">ESTATEFLOW LEADS</p><h2 id="lead-heading">Qualify before booking</h2><p>Keep buyer requirements, consent, and human handoffs in one visible queue.</p></div>
      <button type="button" className="secondary-button compact" onClick={refresh} disabled={loading}><RefreshCw size={14} />Refresh</button>
    </div>
    <div className="lead-intake-grid">
      <form className="lead-form" onSubmit={create}>
        <h3>New lead</h3><p>Save a buyer enquiry. The rules explain what happens next.</p>
        <div className="lead-form-fields">
          <label><span>External enquiry ID</span><input value={externalKey} onChange={(event) => setExternalKey(event.target.value)} maxLength={120} required placeholder="e.g. website-4821" /></label>
          <label><span>Customer name</span><input value={customerName} onChange={(event) => setCustomerName(event.target.value)} maxLength={100} required placeholder="Customer's name" /></label>
          <label><span>Contact email</span><div className="lead-email-field"><Mail size={14} /><input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} type="email" maxLength={254} placeholder="buyer@example.com" /></div></label>
          <label><span>Preferred city</span><input value={city} onChange={(event) => setCity(event.target.value)} maxLength={100} placeholder="e.g. Jaipur" /></label>
          <label><span>Maximum budget (INR)</span><input value={budget} onChange={(event) => setBudget(event.target.value)} type="number" min="1" step="0.01" placeholder="e.g. 15000000" /></label>
          <label><span>Minimum bedrooms</span><input value={bedrooms} onChange={(event) => setBedrooms(event.target.value)} type="number" min="0" max="20" placeholder="Any" /></label>
          <label><span>Buying timeline</span><select value={timeline} onChange={(event) => setTimeline(event.target.value)}><option value="unknown">Not known yet</option><option value="within_month">Within a month</option><option value="within_quarter">Within three months</option><option value="later">Later</option></select></label>
        </div>
        <label className="lead-consent"><input checked={consent} onChange={(event) => setConsent(event.target.checked)} type="checkbox" /><span>The customer agreed to receive follow-up contact.</span></label>
        <button className="primary-button" type="submit" disabled={loading}>{loading ? 'Saving…' : connected ? 'Save lead' : 'Connect to save'}<ArrowRight size={14} /></button>
      </form>
      <div className="lead-queue">
        <div className="lead-queue-heading"><div><h3>Lead queue</h3><p>Current qualification with its reasons</p></div><span>{leads.length} shown</span></div>
        {!connected && <div className="lead-queue-empty"><CircleHelp size={22} /><strong>Connect to see live enquiries</strong><span>No customer details are shown in demo mode.</span></div>}
        {connected && leads.length === 0 && <div className="lead-queue-empty"><CircleHelp size={22} /><strong>No leads loaded</strong><span>Save a lead or refresh this queue.</span></div>}
        {connected && leads.length > 0 && <div className="lead-list">{leads.map((lead) => <article className="lead-row" key={lead.lead_id}>
          <div className="lead-row-top"><div><strong>{lead.customer_name}</strong><span>{lead.city ?? 'City unknown'} · {lead.external_key}</span></div><span className={`lead-status lead-status-${lead.qualification_status}`}>{lead.qualification_status === 'qualified' ? <CheckCircle2 size={12} /> : lead.qualification_status === 'human_review' ? <HandHeart size={12} /> : <CircleHelp size={12} />}{statusText[lead.qualification_status]}</span></div>
          <p>{lead.qualification_reasons.map((reason) => reasonText[reason] ?? reason).join(' · ')}</p>
          <div className="lead-row-foot"><span>Version {lead.current_version} · {lead.timeline.replaceAll('_', ' ')}</span><div className="lead-row-actions">{lead.qualification_status === 'qualified' && <button type="button" disabled={loading} onClick={() => chooseViewing(lead)}><ArrowRight size={13} />Arrange viewing</button>}{lead.qualification_status !== 'human_review' ? <button type="button" disabled={loading} onClick={() => routeToPerson(lead)}><HandHeart size={13} />Request human review</button> : <button type="button" disabled={loading} onClick={() => finishReview(lead)}><CheckCircle2 size={13} />Finish review</button>}</div></div>
        </article>)}</div>}
        {connected && launchLead && <form className="lead-form lead-launch-form" onSubmit={launchViewing}>
          <h3>Arrange a viewing for {launchLead.customer_name}</h3><p>Select an offered property slot. Buyer requirements and availability are checked again before reservation.</p>
          <div className="lead-form-fields">
            <label><span>Scheduling</span><select value={scheduling} onChange={(event) => { setScheduling(event.target.value as 'native' | 'reference'); setLaunchKey(`lead-viewing-${crypto.randomUUID()}`); }} disabled={loading}><option value="native">Native viewing calendar</option><option value="reference">Fictional reference booking</option></select></label>
            {scheduling === 'native' && <>
              <label><span>Offered viewing slot</span><select required value={nativeSlotId} onChange={(event) => { setNativeSlotId(event.target.value); setLaunchKey(`lead-viewing-${crypto.randomUUID()}`); }} disabled={loading}><option value="">Choose an available slot</option>{calendarSlots.map((slot) => <option key={slot.slot_id} value={slot.slot_id}>{new Date(slot.starts_at).toLocaleString()} – {new Date(slot.ends_at).toLocaleTimeString()} · {slot.property_title || `Property ${slot.property_id.slice(0, 8)}`} v{slot.property_version}</option>)}</select></label>
              <div><button type="button" className="secondary-button compact" onClick={enableNativeAgent} disabled={loading || !!nativeVersionId}>{nativeVersionId ? <CheckCircle2 size={14} /> : <RefreshCw size={14} />}{nativeVersionId ? 'Native viewing agent ready' : 'Enable native viewing agent'}</button><p>{calendarSlots.length} available slots loaded. Offer a slot in Viewing calendar if none is suitable. The calendar stores local reservations; external calendar sync is not connected.</p></div>
            </>}
            {scheduling === 'reference' && <>
            <label><span>Agent</span><select required value={agentId} onChange={(event) => chooseAgent(event.target.value)} disabled={loading}><option value="">Choose an agent</option>{agents.map((agent) => <option key={agent.agent_id} value={agent.agent_id}>{agent.display_name}</option>)}</select></label>
            <label><span>Agent version</span><select required value={versionId} onChange={(event) => { setVersionId(event.target.value); setLaunchKey(`lead-viewing-${crypto.randomUUID()}`); }} disabled={loading}><option value="">Choose a version</option>{versions.map((version) => <option key={version.agent_version_id} value={version.agent_version_id}>{version.version}</option>)}</select></label>
            <label><span>Requested time (your local timezone)</span><input required type="datetime-local" value={viewingSlot} onChange={(event) => { setViewingSlot(event.target.value); setLaunchKey(`lead-viewing-${crypto.randomUUID()}`); }} /></label>
            </>}
          </div><div className="lead-launch-actions"><button type="submit" className="primary-button" disabled={loading || (scheduling === 'native' && !nativeVersionId)}>Create viewing run<ArrowRight size={14} /></button><button type="button" className="secondary-button" onClick={() => setLaunchLead(null)}>Cancel</button></div>
        </form>}
      </div>
    </div>
    {error && <p className="property-error" role="alert">{error}</p>}
    {notice && <p className="lead-notice" role="status">{notice}</p>}
  </section>;
}
