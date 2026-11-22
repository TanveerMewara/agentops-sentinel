'use client';

import { CalendarDays, Clock3, Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';

type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };
type Property = { property_id: string; title: string; current_version: number; listing_status: string };
type Slot = { slot_id: string; property_id: string; property_version: number; starts_at: string; ends_at: string; active: boolean; available: boolean };
type Reservation = { reservation_id: string; slot_id: string; status: 'confirmed' | 'cancelled'; created_at: string };
type CalendarCall = { tool_call_id: string; run_id: string; tool_name: string; status: string; run_status: string; manual_desk: boolean; adapter_installed: boolean; arguments: Record<string, unknown>; result: { status?: string; reservation_id?: string | null } | null; error: string | null };
type Actions = { configuration: { agent_version_id: string; tools: Record<string, string> } | null; calls: CalendarCall[] };
type Data = Actions & { role: string; properties: Property[]; slots: Slot[]; reservations: Reservation[] };
type Bound<T> = { request: Props['request']; value: T };

async function load(request: Props['request']): Promise<Data> {
  const identity = await request('/v1/me') as { role: string };
  const actions = await request('/v1/calendar/actions?limit=100') as Actions;
  if (identity.role === 'worker') return { ...actions, role: identity.role, properties: [], slots: [], reservations: [] };
  const [properties, slots, reservations] = await Promise.all([
    request('/v1/properties?limit=100'), request('/v1/calendar/slots?limit=100'), request('/v1/calendar/reservations?limit=100'),
  ]);
  return { ...actions, role: identity.role, properties: properties as Property[], slots: slots as Slot[], reservations: reservations as Reservation[] };
}

function stamp(value: string) {
  return new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function ViewingCalendar({ connected, onConnect, request }: Props) {
  const [snapshot, setSnapshot] = useState<Bound<Data> | null>(null);
  const [notice, setNotice] = useState<Bound<string> | null>(null);
  const [working, setWorking] = useState<Bound<string> | null>(null);
  const [draft, setDraft] = useState<Bound<{ property: string; start: string; duration: string }> | null>(null);
  const current = useRef(request);
  const pendingIntent = useRef<{ request: Props['request']; signature: string; key: string } | null>(null);
  useEffect(() => {
    current.current = request;
    let active = true;
    if (connected) load(request).then((value) => {
      if (active) { setSnapshot({ request, value }); setNotice(null); }
    }).catch((error: unknown) => {
      if (active) setNotice({ request, value: error instanceof Error ? error.message : 'Could not load the calendar.' });
    });
    return () => { active = false; };
  }, [connected, request]);

  const data = connected && snapshot?.request === request ? snapshot.value : null;
  const message = connected && notice?.request === request ? notice.value : '';
  const busy = working?.request === request ? working.value : '';
  const fields = draft?.request === request ? draft.value : { property: '', start: '', duration: '30' };
  const canEdit = !!data && ['admin', 'developer'].includes(data.role);
  const canReview = !!data && ['admin', 'reviewer'].includes(data.role);
  const canExecute = !!data && ['admin', 'worker'].includes(data.role);
  const choices = data?.properties.filter((property) => property.listing_status === 'active') || [];
  const title = (id: string) => data?.properties.find((property) => property.property_id === id)?.title || `Property ${id.slice(0, 8)}`;

  function update(field: keyof typeof fields, value: string) {
    setDraft({ request, value: { ...fields, [field]: value } });
  }

  async function refresh() {
    if (!connected) { onConnect(); return; }
    setWorking({ request, value: 'refresh' });
    try {
      const value = await load(request);
      if (current.current === request) { setSnapshot({ request, value }); setNotice(null); }
    } catch (error: unknown) {
      if (current.current === request) setNotice({ request, value: error instanceof Error ? error.message : 'Could not refresh the calendar.' });
    } finally { if (current.current === request) setWorking(null); }
  }

  async function change(path: string, body?: unknown, success?: string, onRecorded?: () => void) {
    setWorking({ request, value: path });
    let saved = false;
    try {
      await request(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      saved = true;
      if (current.current !== request) return;
      onRecorded?.();
      const value = await load(request);
      if (current.current === request) {
        setSnapshot({ request, value });
        setNotice({ request, value: success || (body ? 'Viewing time offered. A reservation still needs an approved tool action.' : 'Offer withdrawn. Existing reservations are unchanged.') });
      }
    } catch (error: unknown) {
      if (current.current === request) setNotice({ request, value: saved ? 'Action recorded, but refresh failed. Refresh to inspect its current state.' : `${error instanceof Error ? error.message : 'Could not confirm the action.'} Refresh and inspect its state before retrying. Recover uncertain executions using their recorded receipt.` });
    } finally { if (current.current === request) setWorking(null); }
  }

  function proposal(action: 'reserve' | 'cancel', arguments_: Record<string, unknown>) {
    const signature = JSON.stringify({ action, arguments: arguments_ });
    if (pendingIntent.current?.request !== request || pendingIntent.current.signature !== signature) {
      pendingIntent.current = { request, signature, key: crypto.randomUUID() };
    }
    const key = pendingIntent.current.key;
    void change('/v1/calendar/proposals', { action, arguments: arguments_, idempotency_key: key },
      'Proposal recorded. Review and approve the exact action before execution.', () => { pendingIntent.current = null; });
  }

  function act(call: CalendarCall, action: string) {
    const base = `/v1/runs/${call.run_id}`;
    const path = action === 'complete' ? `/v1/calendar/actions/${call.tool_call_id}/close` : `${base}/tool-calls/${call.tool_call_id}/${action}`;
    void change(path, action === 'approve' ? { valid_for_seconds: 300 } : undefined,
      action === 'execute' || action === 'reconcile' ? 'Action result recorded. Inspect the business outcome below; a completed call can still report unavailable.' : action === 'approve' ? 'Exact action approved for five minutes. Execution is a separate step.' : action === 'complete' ? 'Run closed in the ledger.' : 'Review decision recorded.');
  }

  function offer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const property = choices.find((item) => item.property_id === fields.property);
    const start = new Date(fields.start);
    if (!property || !Number.isFinite(start.getTime())) {
      setNotice({ request, value: 'Choose an active property and a valid viewing time. The server checks that it is in the future.' }); return;
    }
    void change('/v1/calendar/slots', {
      property_id: property.property_id, property_version: property.current_version,
      starts_at: start.toISOString(), ends_at: new Date(start.getTime() + Number(fields.duration) * 60000).toISOString(),
    });
  }

  return <section className="viewing-calendar" id="viewing-calendar" aria-labelledby="calendar-title">
    <div className="calendar-heading"><div><div className="calendar-eyebrow"><CalendarDays size={14} /> VIEWING DESK</div>
      <h2 id="calendar-title">Make room for the next viewing.</h2><p>Live offers and reservation records from your organization’s native calendar.</p></div>
      <button className="secondary-button" onClick={refresh} disabled={!!busy}><RefreshCw size={14} />{busy === 'refresh' ? 'Refreshing…' : connected ? 'Refresh calendar' : 'Connect API'}</button>
    </div>
    <div className="calendar-notice" role="status">{message || (!connected ? 'Connect your API to see real calendar records. No sample reservations are shown here.' : !data ? 'Loading calendar…' : '')}</div>
    {data && <>
      <div className="calendar-stats">{data.role !== 'worker' && <><article><span>Available offers</span><strong>{data.slots.filter((slot) => slot.available).length}</strong><small>In the next 100 future offers</small></article>
        <article><span>Confirmed reservations</span><strong>{data.reservations.filter((item) => item.status === 'confirmed').length}</strong><small>In the latest 100 reservation records</small></article>
        </>}<article><span>Your access</span><strong className="calendar-role">{data.role}</strong><small>{canEdit ? 'Propose calendar actions' : canReview ? 'Review exact calendar actions' : 'Execute approved actions and recover receipts'}</small></article></div>
      {canEdit && !data.configuration && <div className="calendar-setup"><div><h3>Enable approved calendar actions</h3><p>Register the manual calendar desk and its two installed tools. This creates no reservation and makes no model call.</p></div><button className="secondary-button" disabled={!!busy} onClick={() => void change('/v1/calendar/configuration', undefined, 'Calendar actions enabled. You can now submit reservation and cancellation proposals.')}><ShieldCheck size={14} />Enable calendar actions</button></div>}
      {data.role !== 'worker' && <div className="calendar-workspace">
        <div className="calendar-agenda"><div className="calendar-section-heading"><h3>Upcoming viewing times</h3><span><Clock3 size={12} /> Your local time</span></div>
          {!data.slots.length && <div className="calendar-empty"><CalendarDays size={27} /><h4>A clear schedule.</h4><p>Offer a viewing time for an active property to start filling this agenda.</p></div>}
          <div className="calendar-slots">{data.slots.map((slot) => <article key={slot.slot_id} className={`calendar-slot ${slot.available ? 'available' : 'unavailable'}`}>
            <div className="calendar-date"><strong>{new Date(slot.starts_at).toLocaleDateString(undefined, { day: '2-digit' })}</strong><span>{new Date(slot.starts_at).toLocaleDateString(undefined, { month: 'short' })}</span></div>
            <div className="calendar-slot-detail"><h4>{title(slot.property_id)}</h4><p>{stamp(slot.starts_at)} – {new Date(slot.ends_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</p>
              <small>Listing v{slot.property_version} · Slot {slot.slot_id.slice(0, 8)}</small></div>
            <div className="calendar-slot-actions"><span className={`calendar-badge ${slot.available ? 'teal' : 'muted'}`}>{!slot.active ? 'Withdrawn' : slot.available ? 'Available' : 'Unavailable'}</span>
              {canEdit && slot.available && <button disabled={!!busy || !data.configuration} onClick={() => proposal('reserve', { slot_id: slot.slot_id, property_id: slot.property_id, property_version: slot.property_version, starts_at: slot.starts_at, ends_at: slot.ends_at })}>Request reservation</button>}
              {canEdit && slot.active && <button disabled={!!busy} onClick={() => void change(`/v1/calendar/slots/${slot.slot_id}/withdraw`)}>Withdraw offer</button>}</div>
          </article>)}</div>
        </div>
        <aside className="calendar-offer"><div className="calendar-section-heading"><h3>Offer a viewing time</h3><Plus size={16} /></div>
          {canEdit ? <form onSubmit={offer}>
            <label htmlFor="calendar-property">Active property</label><select id="calendar-property" required value={fields.property} onChange={(event) => update('property', event.target.value)} disabled={!!busy}>
              <option value="">Choose a property</option>{choices.map((property) => <option key={property.property_id} value={property.property_id}>{property.title} · v{property.current_version}</option>)}</select>
            <label htmlFor="calendar-start">Starts at · your local time</label><input id="calendar-start" type="datetime-local" required value={fields.start} onChange={(event) => update('start', event.target.value)} disabled={!!busy} />
            <label htmlFor="calendar-duration">Viewing duration</label><select id="calendar-duration" value={fields.duration} onChange={(event) => update('duration', event.target.value)} disabled={!!busy}>
              {[15, 30, 45, 60, 90, 120].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}</select>
            <button className="primary-button" type="submit" disabled={!!busy || !choices.length}><Plus size={14} />{busy === '/v1/calendar/slots' ? 'Saving offer…' : 'Offer viewing time'}</button>
            {!choices.length && <p>No active properties in the latest 100 listings. Add or activate a property first.</p>}
            <p>Times are stored in UTC. Offers must start within 180 days. Availability is checked again when reserving.</p>
          </form> : <p className="calendar-help">A developer or administrator can offer and withdraw times. Your key can inspect this calendar.</p>}
          <div className="calendar-approval-note"><ShieldCheck size={17} /><p>Offering a time does not book it. Submit a proposal, review its exact arguments, then execute the approved action. Availability is rechecked when executing.</p></div>
        </aside>
      </div>}
      {data.role !== 'worker' && <div className="calendar-reservations"><div className="calendar-section-heading"><h3>Reservation records</h3><span>Latest 100 · current state</span></div>
        {!data.reservations.length ? <p className="calendar-help">No reservation records yet. Confirmed bookings will appear here after an approved calendar action completes.</p> : <div className="calendar-reservation-list">{data.reservations.map((reservation) => {
          const slot = data.slots.find((item) => item.slot_id === reservation.slot_id);
          return <article key={reservation.reservation_id}><div><h4>{slot ? title(slot.property_id) : `Slot ${reservation.slot_id.slice(0, 8)}`}</h4><p>{slot ? stamp(slot.starts_at) : 'Time outside the loaded future offers'}</p><code>{reservation.reservation_id}</code></div>
            <div className="calendar-slot-actions"><span className={`calendar-badge ${reservation.status === 'confirmed' ? 'teal' : 'muted'}`}>{reservation.status}</span>{canEdit && reservation.status === 'confirmed' && <button disabled={!!busy || !data.configuration} onClick={() => proposal('cancel', { reservation_id: reservation.reservation_id })}>Request cancellation</button>}</div></article>;
        })}</div>}
      </div>}
      <div className="calendar-actions"><div className="calendar-section-heading"><h3>Approval and execution desk</h3><span>Up to 100 actions · Pending first</span></div>
        <p className="calendar-help">Developer: propose. Reviewer: approve, reject, or revoke. Worker: execute or recover. Administrators can perform each step. Approvals expire after five minutes; expired approvals return to review when execution is attempted.</p>
        {!data.calls.length && <p className="calendar-help">No calendar actions yet. Request a reservation from an available offer to start.</p>}
        <div className="calendar-action-list">{data.calls.map((call) => <article key={call.tool_call_id}>
          <header><div><h4>{call.tool_name === 'reserve_viewing_slot' ? 'Reserve a viewing time' : 'Cancel a reservation'}</h4><small>Action {call.tool_call_id.slice(0, 8)} · Run {call.run_id.slice(0, 8)}</small></div><span className={`calendar-badge ${call.status === 'completed' ? 'teal' : 'muted'}`}>{call.status.replaceAll('_', ' ')}</span></header>
          <div className="calendar-exact"><span>Exact action arguments</span><pre>{JSON.stringify(call.arguments, null, 2)}</pre></div>
          {call.result && <div className="calendar-result"><strong>Business outcome: {call.result.status || 'Not reported'}</strong>{call.result.reservation_id && <code>Reservation {call.result.reservation_id}</code>}</div>}
          {call.error && <p className="calendar-help">{call.error}</p>}
          {!call.adapter_installed && <p className="calendar-help">Matching adapter is not installed. Dispatch is unavailable in this deployment.</p>}
          <div className="calendar-action-buttons">
            {canReview && call.status === 'awaiting_approval' && <><button className="primary-button" disabled={!!busy} onClick={() => act(call, 'approve')}><ShieldCheck size={13} />Approve exact action</button><button className="secondary-button" disabled={!!busy} onClick={() => act(call, 'reject')}>Reject</button></>}
            {canReview && call.status === 'authorized' && <button className="secondary-button" disabled={!!busy} onClick={() => act(call, 'revoke')}>Revoke approval</button>}
            {canExecute && call.status === 'authorized' && <button className="primary-button" disabled={!!busy || !call.adapter_installed} onClick={() => act(call, 'execute')}>Execute approved action</button>}
            {canExecute && ['unknown', 'executing'].includes(call.status) && <button className="secondary-button" disabled={!!busy || !call.adapter_installed} onClick={() => act(call, 'reconcile')}>Recover from receipt</button>}
            {canExecute && call.manual_desk && ['completed', 'failed', 'cancelled'].includes(call.status) && ['queued', 'running'].includes(call.run_status) && <button className="secondary-button" disabled={!!busy} onClick={() => act(call, 'complete')}>Close run</button>}
          </div>
          {call.status === 'executing' && <p className="calendar-help">Recovery waits for the current execution lease to expire. An active lease returns a conflict.</p>}
          {call.status === 'needs_review' && <p className="calendar-help">Evidence needs investigation. Do not replay this action to guess its outcome.</p>}
        </article>)}</div>
      </div>
      <footer className="calendar-foot">Native property capacity · No external calendar sync or invitations · Refresh to update availability</footer>
    </>}
  </section>;
}
