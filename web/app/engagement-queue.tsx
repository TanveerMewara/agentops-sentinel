'use client';

import { CheckCircle2, MailCheck, RefreshCw, Send, UsersRound } from 'lucide-react';
import { type FormEvent, useEffect, useState } from 'react';

type Contact = { crm_contact_id: string; lead_id: string; stage: string; booking_id: string | null; updated_at: string };
type Draft = { draft_id: string; lead_id: string; revision: number; status: 'draft' | 'approved' | 'cancelled'; recipient: string; subject: string; body: string; created_at: string };
type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };

export default function EngagementQueue({ connected, onConnect, request }: Props) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');

  async function load() {
    if (!connected) { onConnect(); return; }
    setBusy(true); setError(null);
    try {
      const [contactData, draftData] = await Promise.all([
        request('/v1/crm/contacts?limit=20'), request('/v1/followups?limit=20'),
      ]);
      setContacts(contactData as Contact[]); setDrafts(draftData as Draft[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not load engagement records.'); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    let active = true;
    if (!connected) return;
    Promise.all([request('/v1/crm/contacts?limit=20'), request('/v1/followups?limit=20')])
      .then(([contactData, draftData]) => { if (active) { setContacts(contactData as Contact[]); setDrafts(draftData as Draft[]); } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load engagement records.'); });
    return () => { active = false; };
  }, [connected, request]);

  async function approve(draft: Draft) {
    setBusy(true); setError(null);
    try {
      await request(`/v1/followups/${draft.draft_id}/approve`, { method: 'POST', body: JSON.stringify({ expected_revision: draft.revision }) });
      setDrafts(await request('/v1/followups?limit=20') as Draft[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'A reviewer key is required to approve this draft.'); }
    finally { setBusy(false); }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    setBusy(true); setError(null);
    try {
      await request(`/v1/followups/${editing.draft_id}`, { method: 'PATCH',
        body: JSON.stringify({ expected_revision: editing.revision, subject, body: message }) });
      setEditing(null);
      setDrafts(await request('/v1/followups?limit=20') as Draft[]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save draft.'); }
    finally { setBusy(false); }
  }

  return <section className="engagement-queue panel" id="engagement-queue" aria-labelledby="engagement-heading">
    <div className="engagement-head"><div className="engagement-icon"><MailCheck size={19} /></div><div><p className="property-eyebrow">CUSTOMER ENGAGEMENT</p><h2 id="engagement-heading">CRM and follow-up review</h2><p>Confirmed viewings create reviewable drafts. Sending remains disabled until a delivery integration is installed.</p></div><button className="secondary-button compact" onClick={load} disabled={busy}><RefreshCw size={14} />Refresh</button></div>
    {!connected ? <button className="engagement-connect" onClick={onConnect}>Connect the API to view CRM activity</button> : <div className="engagement-columns">
      <div><div className="engagement-title"><UsersRound size={15} /><strong>CRM contacts</strong><span>{contacts.length}</span></div>{contacts.length ? contacts.map((contact) => <article className="crm-row" key={contact.crm_contact_id}><div><strong>{contact.stage.replaceAll('_', ' ')}</strong><span>Lead {contact.lead_id.slice(0, 8).toUpperCase()}</span></div>{contact.booking_id && <code>{contact.booking_id}</code>}</article>) : <p className="engagement-empty">No viewing has created a CRM contact yet.</p>}</div>
      <div><div className="engagement-title"><Send size={15} /><strong>Follow-up drafts</strong><span>{drafts.length}</span></div>{drafts.length ? drafts.map((draft) => <article className="draft-row" key={draft.draft_id}><div className="draft-row-head"><div><strong>{draft.subject}</strong><span>{draft.recipient} · Revision {draft.revision}</span></div><span className={`draft-state ${draft.status}`}>{draft.status === 'approved' && <CheckCircle2 size={11} />}{draft.status}</span></div><p>{draft.body}</p><div className="draft-actions">{draft.status === 'draft' && <button disabled={busy} onClick={() => approve(draft)}><CheckCircle2 size={13} />Approve revision</button>}{draft.status !== 'cancelled' && <button disabled={busy} onClick={() => { setEditing(draft); setSubject(draft.subject); setMessage(draft.body); }}>Edit draft</button>}</div></article>) : <p className="engagement-empty">No follow-up drafts yet.</p>}</div>
    </div>}
    {editing && <form className="draft-editor" onSubmit={saveEdit}><h3>Edit follow-up</h3><p>Saving creates a new revision and requires fresh approval.</p><label>Subject<input required maxLength={300} value={subject} onChange={(event) => setSubject(event.target.value)} /></label><label>Message<textarea required maxLength={10000} rows={7} value={message} onChange={(event) => setMessage(event.target.value)} /></label><div><button className="primary-button" disabled={busy}>Save revision</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button></div></form>}
    {error && <p className="property-error" role="alert">{error}</p>}
  </section>;
}
