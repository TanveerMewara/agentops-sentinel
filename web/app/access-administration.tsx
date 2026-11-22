'use client';
import { type FormEvent, useEffect, useState } from 'react';
import { KeyRound, RefreshCw, Copy, ShieldCheck } from 'lucide-react';

type Identity = { organization_id: string; organization_name: string; role: string; api_key_id: string };
type Key = { api_key_id: string; key_prefix: string; label: string; role: string; revoked_at: string | null; expires_at: string | null };
type Event = { event_id: number; event_type: string; target_key_id: string; created_at: string };
type Props = { connected: boolean; onConnect: () => void; request: (path: string, init?: RequestInit) => Promise<unknown> };

export default function AccessAdministration({ connected, onConnect, request }: Props) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [token, setToken] = useState<string | null>(null);
  const [label, setLabel] = useState('');
  const [role, setRole] = useState('developer');
  const [expiration, setExpiration] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function reload() {
    const who = await request('/v1/me') as Identity;
    const [keyData, eventData] = who.role === 'admin' ? await Promise.all([
      request('/v1/access/keys'), request('/v1/access/events?limit=15')]) : [[], []];
    setIdentity(who); setKeys(keyData as Key[]); setEvents(eventData as Event[]);
  }

  useEffect(() => {
    let active = true;
    if (connected) request('/v1/me').then(async (value) => {
      const who = value as Identity;
      const [keyData, eventData] = who.role === 'admin' ? await Promise.all([
        request('/v1/access/keys'), request('/v1/access/events?limit=15')]) : [[], []];
      if (active) { setIdentity(who); setKeys(keyData as Key[]); setEvents(eventData as Event[]); setToken(null); }
    }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load access.'); });
    return () => { active = false; };
  }, [connected, request]);

  async function refresh() {
    if (!connected) { onConnect(); return; }
    setBusy(true); setError(null);
    try { await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not refresh.'); }
    finally { setBusy(false); }
  }

  async function issue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setToken(null); setCopied(false);
    try {
      const result = await request('/v1/access/keys', { method: 'POST', body: JSON.stringify({ label, role,
        expires_at: expiration ? new Date(expiration).toISOString() : null }) }) as { token: string };
      setToken(result.token); setLabel(''); setExpiration(''); await reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not issue key.'); }
    finally { setBusy(false); }
  }

  async function revoke(key: Key) {
    setBusy(true); setError(null);
    try { await request(`/v1/access/keys/${key.api_key_id}/revoke`, { method: 'POST', body: '{}' }); await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not revoke key.'); }
    finally { setBusy(false); }
  }

  async function copy() {
    if (!token) return;
    try { await navigator.clipboard.writeText(token); setCopied(true); }
    catch { setError('Clipboard access failed. Select and copy the displayed token.'); }
  }

  return <section className="access-administration panel" id="access-administration" aria-labelledby="access-heading"><div className="access-head"><KeyRound size={22} /><div><p className="property-eyebrow">WORKSPACE ACCESS</p><h2 id="access-heading">Keys and permissions</h2><p>Separate developer, reviewer, worker, and administrator access.</p></div><button className="secondary-button compact" disabled={busy} onClick={refresh}><RefreshCw size={14} />Refresh</button></div>
    {!connected ? <button className="engagement-connect" onClick={onConnect}>Connect the API to manage access</button> : <><div className="access-identity"><ShieldCheck size={16} /><strong>{identity?.organization_name ?? 'Loading identity…'}</strong><span>{identity?.role}</span></div>{identity?.role === 'admin' ? <><form className="access-form" onSubmit={issue}><label>Key label<input required maxLength={100} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Property team reviewer" /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value)}>{['developer', 'reviewer', 'worker', 'admin'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Expires at (optional, local time)<input type="datetime-local" value={expiration} onChange={(event) => setExpiration(event.target.value)} /></label><button className="primary-button" disabled={busy}>Create key</button></form>
    {token && <div className="access-token"><strong>Copy this key now</strong><p>Shown once. Store it securely; it is not saved in browser storage.</p><code>{token}</code><div><button className="secondary-button" onClick={copy}><Copy size={13} />{copied ? 'Copied' : 'Copy key'}</button><button className="secondary-button" onClick={() => setToken(null)}>Dismiss</button></div></div>}
    <div className="access-key-list">{keys.map((key) => <article key={key.api_key_id}><div><strong>{key.label}</strong><code>{key.key_prefix}</code></div><span>{key.role}</span><small>{key.revoked_at ? 'Revoked' : key.expires_at ? `Expires ${new Date(key.expires_at).toLocaleString()}` : 'No expiry'}</small>{!key.revoked_at && <button className="secondary-button compact" disabled={busy || key.api_key_id === identity.api_key_id} onClick={() => revoke(key)}>Revoke</button>}</article>)}</div><div className="access-audit"><h3>Access audit</h3>{events.map((event) => <p key={event.event_id}><strong>{event.event_type}</strong><code>{event.target_key_id.slice(0, 8)}</code><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time></p>)}</div></> : <p className="access-note">Key administration requires an administrator key. Your current role can use its assigned platform capabilities.</p>}</>}{error && <p className="property-error" role="alert">{error}</p>}</section>;
}
