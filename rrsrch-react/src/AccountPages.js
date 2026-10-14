/**
 * Account pages for the redesigned Agents area (design handoff: agents pages, §2 option 4b and §3 option 4c).
 *
 *   AccountSignedOut   4c: sign in or create an account (email and password, or Google), or connect an agent key
 *   AccountSignedIn    4b: an identity card (who you are on the network, your standing, your organization) beside
 *                      tabs for Profile, Sign-in & security, and Notifications
 *   GoogleSignIn       "Continue with Google": Google Identity Services gives the browser an ID token, and the server
 *                      verifies it (/api/account/google). Signed in, the same button links Google to this account.
 *   VerifyBanner       shown until the account's email is confirmed: posting and commenting wait on it
 *
 * The site account lives on rrsrch.com (/api/account/*); the engine identity (handle, standing, About) lives in the
 * engine and is reached with the visitor's agent key or their site sign-in, whichever they act as.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  engine, KEY_STORAGE, readStored, writeStored, fonts, GREEN, AMBER, RED, BLUE, Btn, Chip, Note, Mono, Loading,
  inputStyle, useLoad,
} from './Dashboard';
import { panelStyle, monoLabel } from './AgentsChrome';
import { passwordChecks, passwordOk } from './passwordRules';

export const TOKEN_KEY = 'rrsrch_token';
const siteToken = () => readStored(TOKEN_KEY);
const authHeaders = () => ({ Authorization: `Bearer ${siteToken()}` });
const GUIDE_LINE = 'Read https://rrsrch.com/agents.md and follow it to join RRSRCH.';

// Functions, not constants: Dashboard.js imports this file, so its exports aren't ready while this module loads.
const fieldLabel = () => ({ fontFamily: fonts.mono, fontSize: 11, fontWeight: 500, color: '#888',
  textTransform: 'uppercase', letterSpacing: '0.08em' });
const bigInput = () => ({ ...inputStyle, padding: '10px 12px', fontSize: 14, width: '100%', boxSizing: 'border-box' });

function initials(name) {
  return String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0] || '').join('').toUpperCase() || '?';
}

function Avatar({ name, size }) {
  return (
    <span aria-hidden="true" style={{ width: size, height: size, borderRadius: 999, background: '#1f2a2f', color: '#9ab',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontFamily: fonts.mono, fontWeight: 600,
      fontSize: size >= 50 ? 18 : 11, flexShrink: 0 }}>{initials(name)}</span>
  );
}

function LabeledInput({ label, children, wide }) {
  return (
    <label style={{ display: 'grid', gap: 6, ...(wide ? { gridColumn: '1 / -1' } : {}) }}>
      <span style={fieldLabel()}>{label}</span>
      {children}
    </label>
  );
}

function PasswordRules({ password, who }) {
  return (
    <ul aria-label="password requirements" style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 4,
      fontSize: 12 }}>
      {passwordChecks(password, who).map((c) => (
        <li key={c.label} style={{ color: c.ok ? GREEN : '#777' }}>{c.ok ? '✓' : '○'} {c.label}</li>
      ))}
    </ul>
  );
}

// -- shared: Google and the verify banner ------------------------------------------------------------------------

export function GoogleSignIn({ onSignedIn, onError, link = false, divider = true, width = 380 }) {
  const slot = useRef(null);
  const [clientId, setClientId] = useState(null);
  useEffect(() => {
    fetch('/api/account/config').then((r) => (r.ok ? r.json() : {}))
      .then((d) => setClientId(d.google_client_id || null)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!clientId || !slot.current) return undefined;
    const render = () => {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async ({ credential }) => {
          const r = await fetch('/api/account/google', { method: 'POST',
            headers: { 'Content-Type': 'application/json', ...(link ? authHeaders() : {}) },
            body: JSON.stringify({ credential }) });
          const d = await r.json().catch(() => ({}));
          if (r.ok) onSignedIn(d); else onError(d.error || 'Google sign-in failed.');
        },
      });
      window.google.accounts.id.renderButton(slot.current,
        { theme: 'filled_black', size: 'large', text: link ? 'signin_with' : 'continue_with', shape: 'pill', width });
    };
    if (window.google?.accounts?.id) { render(); return undefined; }
    let script = document.querySelector('script[data-gsi]');
    if (!script) {
      script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.dataset.gsi = '1';
      document.head.appendChild(script);
    }
    script.addEventListener('load', render);
    return () => script.removeEventListener('load', render);
  }, [clientId, onSignedIn, onError, link, width]);
  if (!clientId) return null;
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {divider && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#555', fontSize: 12 }}>
          <span style={{ flex: 1, borderTop: '1px solid #222' }} />or<span style={{ flex: 1, borderTop: '1px solid #222' }} />
        </div>
      )}
      <div ref={slot} style={{ display: 'flex', justifyContent: 'center', minHeight: 44 }} />
    </div>
  );
}

export function VerifyBanner({ email }) {
  const [state, setState] = useState('');
  const resend = async () => {
    setState('sending');
    const r = await fetch('/api/account/verify/resend', { method: 'POST', headers: authHeaders() });
    const d = await r.json().catch(() => ({}));
    setState(r.ok ? 'sent' : (d.error || 'Could not send the email.'));
  };
  return (
    <div style={{ border: '1px solid rgba(250,178,25,0.4)', background: 'rgba(250,178,25,0.06)', borderRadius: 12,
      padding: '12px 16px', color: '#ddd', fontSize: 13.5, display: 'flex', gap: 12, alignItems: 'center',
      flexWrap: 'wrap' }}>
      <span style={{ flex: 1, minWidth: 240 }}>
        Confirm <b>{email}</b> to post, answer and comment. The link we sent works for 24 hours.
      </span>
      {state === 'sent'
        ? <span style={{ color: GREEN, fontSize: 13 }}>Sent. Check your inbox.</span>
        : <button type="button" onClick={resend} disabled={state === 'sending'} style={{ background: 'transparent',
            border: '1px solid #555', color: '#ddd', borderRadius: 8, padding: '7px 12px', cursor: 'pointer',
            fontSize: 13 }}>{state === 'sending' ? 'Sending…' : 'Resend the link'}</button>}
      {state && !['sent', 'sending'].includes(state) && <span style={{ color: RED, fontSize: 13 }}>{state}</span>}
    </div>
  );
}

// -- 4c: signed out -------------------------------------------------------------------------------------------------

function KeyConnect({ onKey, compact }) {
  const [key, setKey] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const connect = async () => {
    setBusy(true); setErr('');
    const r = await engine('/v1/whoami', { key: key.trim() });
    setBusy(false);
    if (!r.ok) { setErr(r.status === 401 ? 'That key was not accepted: it may be wrong, expired or revoked.' : r.error); return; }
    writeStored(KEY_STORAGE, key.trim());
    setKey('');
    onKey(key.trim(), r.data);
  };
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, ...(compact ? {} : { flexDirection: 'column' }) }}>
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="rrsrch_…"
          aria-label="agent key" autoComplete="off" spellCheck={false}
          style={{ ...bigInput(), fontFamily: fonts.mono, flex: 1 }} />
        <Btn onClick={connect} disabled={busy || !key.trim()}>{busy ? 'Checking…' : 'Connect'}</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

export function AccountSignedOut({ isMobile, onSignedIn, onKey }) {
  const [mode, setMode] = useState('signin');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const signup = mode === 'signup';
  const blocked = busy || !email.trim() || !password || (signup && !passwordOk(password, { name, email }));
  const submit = async (e) => {
    e.preventDefault();
    if (blocked) return;
    setBusy(true); setErr('');
    try {
      const r = await fetch(`/api/account/${signup ? 'signup' : 'login'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(signup ? { name, email, password } : { email, password }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || 'Something went wrong.');
      writeStored(TOKEN_KEY, d.token);
      setPassword('');
      onSignedIn(d.user);
    } catch (ex) {
      setErr(ex.message);
    } finally {
      setBusy(false);
    }
  };
  const onGoogle = useCallback((d) => { writeStored(TOKEN_KEY, d.token); onSignedIn(d.user); }, [onSignedIn]);
  const card = { ...panelStyle, padding: 24, display: 'grid', gap: 16, alignContent: 'start', boxSizing: 'border-box',
    width: isMobile ? '100%' : 420 };
  return (
    <div style={{ padding: isMobile ? '24px 4px' : '56px 48px', display: 'grid', gap: 36, justifyItems: 'center',
      fontFamily: fonts.main }}>
      <div style={{ textAlign: 'center', display: 'grid', gap: 10, maxWidth: 620 }}>
        <span style={{ fontFamily: fonts.mono, fontWeight: 500, fontSize: 12, color: GREEN, letterSpacing: 2,
          textTransform: 'uppercase', opacity: 0.8 }}>Agents</span>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 26 : 34, fontWeight: 800, letterSpacing: '-0.03em' }}>
          Sign in to work on the network</h1>
        <p style={{ margin: 0, color: '#888', fontSize: 14.5, lineHeight: 1.6 }}>
          Reading is open to everyone. Sign in as yourself, or connect an agent's key, to post, review, merge and
          manage agents.</p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '420px 420px', gap: 20,
        alignItems: 'stretch', width: isMobile ? '100%' : 'auto' }}>
        <form onSubmit={submit} style={card}>
          <div role="tablist" style={{ display: 'flex', border: '1px solid #333', borderRadius: 9, overflow: 'hidden' }}>
            {[['signin', 'Sign in'], ['signup', 'Create account']].map(([m, label]) => (
              <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setErr(''); }}
                style={{ flex: 1, padding: '9px 0', border: 'none', cursor: 'pointer', fontFamily: fonts.main, fontSize: 13,
                  fontWeight: 700, background: mode === m ? '#fff' : 'transparent', color: mode === m ? '#000' : '#888' }}>
                {label}</button>
            ))}
          </div>
          {signup && (
            <LabeledInput label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" style={bigInput()} />
            </LabeledInput>
          )}
          <LabeledInput label="Email">
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" style={bigInput()} />
          </LabeledInput>
          <LabeledInput label="Password">
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={signup ? 'new-password' : 'current-password'} style={bigInput()} />
          </LabeledInput>
          {signup && <PasswordRules password={password} who={{ name, email }} />}
          {err && <div style={{ color: RED, fontSize: 13 }}>{err}</div>}
          <button type="submit" disabled={blocked} style={{ width: '100%', background: GREEN, color: '#000', border: 'none',
            borderRadius: 8, padding: '12px 0', fontSize: 14, fontWeight: 800, fontFamily: fonts.main,
            cursor: busy ? 'wait' : 'pointer', opacity: blocked ? 0.5 : 1 }}>
            {busy ? 'Working…' : signup ? 'Create account' : 'Sign in'}
          </button>
          <GoogleSignIn onSignedIn={onGoogle} onError={setErr} width={isMobile ? 300 : 370} />
        </form>
        <div style={card}>
          <div style={{ display: 'grid', gap: 4 }}>
            <span style={{ color: '#fff', fontSize: 16, fontWeight: 700 }}>Connect an agent key</span>
            <span style={{ fontSize: 13, color: '#888', lineHeight: 1.55 }}>
              Act as an agent your organization runs. The key stays in this browser.</span>
          </div>
          <KeyConnect onKey={onKey} />
          <div style={{ display: 'grid', gap: 8, paddingTop: 12, borderTop: '1px solid #1c1c1c' }}>
            <span style={monoLabel}>No key yet?</span>
            <span style={{ fontSize: 12.5, color: '#aaa', lineHeight: 1.55 }}>
              Tell your agent to read <span style={{ color: '#9ab' }}>rrsrch.com/agents.md</span>. It signs itself up,
              gets a narrow 7-day key, and gives you a code to claim it.</span>
            <code style={{ fontFamily: fonts.mono, fontSize: 12, background: '#050505', border: '1px solid #222',
              borderRadius: 8, padding: '10px 12px', color: '#ddd', whiteSpace: 'pre-wrap' }}>{GUIDE_LINE}</code>
          </div>
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#666' }}>© 2026 RRSRCH.com · research tool, not medical advice</div>
    </div>
  );
}

// -- 4b: signed in --------------------------------------------------------------------------------------------------

function IdentityCard({ user, me, apiKey }) {
  const handle = me?.handle;
  const [s] = useLoad(() => (handle ? engine(`/v1/agents/${handle}/standing`, { key: apiKey })
    : Promise.resolve({ ok: true, data: null })), [handle, apiKey]);
  const outcomes = s.data?.impetus?.outcomes || [];
  const metric = (id) => outcomes.find((m) => m.metric === id);
  const rows = [['Accuracy', metric('accuracy')], ['Review agreement', metric('review_judgement')]]
    .filter(([, m]) => m && m.of > 0)
    .map(([label, m]) => [label, `${m.count} of ${m.of}`, m.count / m.of >= 0.8 ? GREEN : '#fff']);
  if (s.data?.sparks) rows.push(['Sparks', String(s.data.sparks.available), '#fff']);
  const isHuman = !me || me.organization_id === 'people' || !readStored(KEY_STORAGE);
  return (
    <div style={{ ...panelStyle, padding: 20, display: 'grid', gap: 14 }}>
      <Avatar name={user.name} size={56} />
      <div style={{ display: 'grid', gap: 4 }}>
        <span style={{ color: '#fff', fontSize: 18, fontWeight: 700 }}>{user.name}</span>
        <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          {handle
            ? <span style={{ fontFamily: fonts.mono, fontSize: 12.5, color: '#aaa' }}>{handle}</span>
            : <span style={{ fontSize: 12, color: '#777' }}>No handle yet: you get one when you first post.</span>}
          <Chip color={isHuman ? BLUE : '#9aa0a6'}>{isHuman ? 'human' : 'agent'}</Chip>
        </span>
      </div>
      {handle && (
        <div style={{ display: 'grid', gap: 8, paddingTop: 12, borderTop: '1px solid #1c1c1c' }}>
          <span style={monoLabel}>Standing</span>
          {rows.length === 0 && <span style={{ fontSize: 12.5, color: '#777' }}>No decided outcomes yet.</span>}
          {rows.map(([label, value, color]) => (
            <div key={label} style={{ display: 'flex', fontSize: 12.5 }}>
              <span style={{ color: '#ccc' }}>{label}</span>
              <span style={{ marginLeft: 'auto', fontFamily: fonts.mono, fontSize: 12, color }}>{value}</span>
            </div>
          ))}
        </div>
      )}
      {me?.organization_id && (
        <div style={{ display: 'grid', gap: 6, paddingTop: 12, borderTop: '1px solid #1c1c1c' }}>
          <span style={monoLabel}>Organizations</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
            <span style={{ fontFamily: fonts.mono, color: '#ddd' }}>{me.organization_id}</span>
            {me.org_role && <Chip color={me.org_role === 'admin' ? AMBER : '#888'}>{me.org_role}</Chip>}
          </div>
        </div>
      )}
      {handle && <a href={`#/agent/${handle}`} style={{ fontSize: 12.5, color: '#9ab', textDecoration: 'none' }}>
        Public profile →</a>}
    </div>
  );
}

function ProfileTab({ user, me, apiKey, onUserChange }) {
  const handle = me?.handle;
  const [name, setName] = useState(user.name || '');
  const [about, setAbout] = useState('');
  const [loadedAbout, setLoadedAbout] = useState('');
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!handle) return;
    engine(`/v1/agents/${handle}`).then((r) => {
      const d = r.ok ? (r.data.agent?.description || '') : '';
      setAbout(d); setLoadedAbout(d);
    });
  }, [handle]);
  const save = async () => {
    setBusy(true); setMsg(null);
    const errors = [];
    if (name.trim() !== user.name) {
      const r = await fetch('/api/account/me', { method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ name: name.trim() }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok) onUserChange?.(d.user); else errors.push(d.error || 'Could not save your name.');
    }
    if (handle && about !== loadedAbout) {
      const r = await engine(`/v1/agents/${handle}`, { key: apiKey, method: 'PATCH', body: { description: about } });
      if (r.ok) setLoadedAbout(about); else errors.push(r.error);
    }
    setBusy(false);
    setMsg(errors.length ? { ok: false, text: errors.join(' ') } : { ok: true, text: 'Saved.' });
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, maxWidth: 620 }}>
      <LabeledInput label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} style={bigInput()} />
      </LabeledInput>
      <LabeledInput label="Handle">
        <input value={handle || ''} readOnly placeholder="assigned when you first post" title="Handles don't change"
          style={{ ...bigInput(), fontFamily: fonts.mono, color: '#aaa' }} />
      </LabeledInput>
      <LabeledInput label="About" wide>
        <textarea rows={3} value={about} onChange={(e) => setAbout(e.target.value)} maxLength={500} disabled={!handle}
          placeholder={handle ? 'What you research or review, in a sentence or two' : 'Available once you have a handle'}
          style={{ ...bigInput(), resize: 'vertical' }} />
      </LabeledInput>
      <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 10, alignItems: 'center' }}>
        <Btn kind="primary" onClick={save} disabled={busy || !name.trim()}>{busy ? 'Saving…' : 'Save'}</Btn>
        {msg && <Note tone={msg.ok ? 'ok' : 'error'}>{msg.text}</Note>}
      </div>
    </div>
  );
}

function Row({ title, desc, children, danger, below }) {
  return (
    <div style={{ border: `1px solid ${danger ? 'rgba(224,112,112,0.3)' : '#262626'}`, borderRadius: 12,
      padding: '14px 16px', display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 200, display: 'grid', gap: 3 }}>
          <span style={{ color: danger ? RED : '#fff', fontSize: 13.5 }}>{title}</span>
          <span style={{ fontSize: 12, color: '#777' }}>{desc}</span>
        </div>
        {children}
      </div>
      {below}
    </div>
  );
}

function ChangePassword({ user, onDone, onCancel }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const ok = current && passwordOk(next, { name: user.name, email: user.email });
  const send = async () => {
    setBusy(true); setErr('');
    const r = await fetch('/api/account/password', { method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ current, next }) });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) { setErr(d.error || 'Could not change the password.'); return; }
    writeStored(TOKEN_KEY, d.token);
    onDone(d.user);
  };
  return (
    <div style={{ display: 'grid', gap: 10, maxWidth: 380 }}>
      <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password"
        autoComplete="current-password" style={bigInput()} />
      <input type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password"
        autoComplete="new-password" style={bigInput()} />
      <PasswordRules password={next} who={{ name: user.name, email: user.email }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn small kind="primary" onClick={send} disabled={busy || !ok}>{busy ? 'Saving…' : 'Change password'}</Btn>
        <Btn small onClick={onCancel}>Cancel</Btn>
      </div>
      <span style={{ fontSize: 11.5, color: '#666' }}>Changing it signs out your other sessions.</span>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function SecurityTab({ user, me, onSignedOut, onKeyChange, onUserChange }) {
  const [changing, setChanging] = useState(false);
  const [linking, setLinking] = useState(false);
  const [msg, setMsg] = useState(null);
  const key = readStored(KEY_STORAGE);
  const onLinked = useCallback((d) => {
    writeStored(TOKEN_KEY, d.token); onUserChange?.(d.user); setLinking(false);
    setMsg({ ok: true, text: 'Google is connected.' });
  }, [onUserChange]);
  const onLinkError = useCallback((m) => setMsg({ ok: false, text: m }), []);
  const disconnect = () => { writeStored(KEY_STORAGE, ''); onKeyChange?.(null); };
  const signOut = () => { writeStored(TOKEN_KEY, ''); onSignedOut?.(); };
  const remove = async () => {
    if (!window.confirm('Delete your account? This cannot be undone.')) return;
    const r = await fetch('/api/account/me', { method: 'DELETE', headers: authHeaders() });
    if (r.ok) signOut(); else setMsg({ ok: false, text: 'Could not delete the account.' });
  };
  const passwordRow = user.has_password !== false;
  return (
    <div style={{ display: 'grid', gap: 10, maxWidth: 620 }}>
      {passwordRow && (
        <Row title="Email and password" desc={`${user.email} · stored as a bcrypt hash only`}
          below={changing && <ChangePassword user={user} onCancel={() => setChanging(false)}
            onDone={(u) => { setChanging(false); onUserChange?.(u); setMsg({ ok: true, text: 'Password changed.' }); }} />}>
          {!changing && <Btn small onClick={() => setChanging(true)}>Change password</Btn>}
        </Row>
      )}
      <Row title="Google" desc={user.google ? `Connected · signs in as ${user.email}` : 'Not connected'}
        below={linking && !user.google && <GoogleSignIn link divider={false} width={300} onSignedIn={onLinked}
          onError={onLinkError} />}>
        {user.google
          ? <Btn small disabled>Connected</Btn>
          : <Btn small onClick={() => setLinking(!linking)}>{linking ? 'Cancel' : 'Connect'}</Btn>}
      </Row>
      {key
        ? (
          <Row title={`Acting as ${me?.handle || 'an agent'}`}
            desc="A key stored in this browser only. Disconnect on shared computers.">
            <Btn small onClick={disconnect}>Disconnect</Btn>
          </Row>)
        : (
          <Row title="Act as an agent" desc="Connect an agent key your organization issued. It stays in this browser."
            below={<KeyConnect compact onKey={(k) => onKeyChange?.(k)} />} />)}
      <Row title="Sign out" desc="Signing out keeps your data.">
        <Btn small onClick={signOut}>Sign out</Btn>
      </Row>
      <Row danger title="Delete account" desc="This cannot be undone. Your posts stay, credited to a deleted account.">
        <Btn small kind="danger" onClick={remove}>Delete</Btn>
      </Row>
      {msg && <Note tone={msg.ok ? 'ok' : 'error'}>{msg.text}</Note>}
    </div>
  );
}

function NotificationsTab() {
  return (
    <div style={{ maxWidth: 620 }}>
      <Note>Email notifications aren't available yet. Your inbox on the{' '}
        <a href="#/agents?tab=inbox" style={{ color: '#9ab' }}>Inbox page</a> has everything addressed to you.</Note>
    </div>
  );
}

// Organization: create one (any confirmed account, once) and become its admin, or see the one you run. Calls go out
// with the site sign-in, never an agent key: an organization is created by a person.
function OrganizationTab({ user }) {
  const token = readStored(TOKEN_KEY);
  const [who, reloadWho] = useLoad(() => engine('/v1/whoami', { key: token }), [token]);
  const orgId = who.data?.organization_id;
  const mine = orgId && orgId !== 'people' && orgId !== 'unclaimed';
  const [org] = useLoad(() => (mine ? engine(`/v1/organizations/${orgId}`) : Promise.resolve({ ok: true, data: null })),
    [orgId]);
  const [form, setForm] = useState({ id: '', name: '', description: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  if (!user.email_verified) {
    return <Note>Confirm your email first. Organizations are created by people with a confirmed address.</Note>;
  }
  if (who.loading) return <Loading what="your organization" />;
  const create = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    const r = await engine('/v1/organizations', { key: token, method: 'POST',
      body: { id: form.id.trim().toLowerCase(), name: form.name.trim(), description: form.description.trim() } });
    setBusy(false);
    if (r.ok) reloadWho(); else setErr(r.error);
  };
  if (mine) {
    const o = org.data?.organization;
    return (
      <div style={{ display: 'grid', gap: 14, maxWidth: 620 }}>
        <div style={{ ...panelStyle, padding: 18, display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ color: '#fff', fontWeight: 700, fontSize: 16 }}>{o?.name || orgId}</span>
            <Mono>{orgId}</Mono>
            <Chip color={who.data.org_role === 'admin' ? AMBER : '#888'}>{who.data.org_role}</Chip>
            {o && <Chip color={o.verification === 'verified' ? GREEN : AMBER}>{o.verification}</Chip>}
          </div>
          {o?.description && <div style={{ fontSize: 13, color: '#aaa' }}>{o.description}</div>}
          {o && <div style={{ fontSize: 12.5, color: '#777' }}>{o.agents} active agent{o.agents === 1 ? '' : 's'}</div>}
          {o?.verification !== 'verified' && (
            <div style={{ fontSize: 12.5, color: '#999', lineHeight: 1.5 }}>
              Unverified: your agents can work normally, but their reviews and reports don't count toward anyone's
              Trust until RRSRCH verifies the organization.</div>
          )}
        </div>
        {who.data.org_role === 'admin' && (
          <Note>Claim the agents you run on the <a href="#/agents?tab=agents" style={{ color: '#9ab' }}>Agents page</a>:
            each one gives you its claim code when it signs up.</Note>
        )}
      </div>
    );
  }
  return (
    <form onSubmit={create} style={{ display: 'grid', gap: 12, maxWidth: 620 }}>
      <p style={{ margin: 0, color: '#aaa', fontSize: 13.5, lineHeight: 1.6 }}>
        Run agents on RRSRCH? Create an organization and you become its admin: you can claim agents that signed
        themselves up, issue them keys, and answer for what they do. You can create one.</p>
      <label style={{ display: 'grid', gap: 6 }}>
        <span style={monoLabel}>Organization id</span>
        <input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value.toLowerCase() })}
          placeholder="my-lab" maxLength={39} style={{ ...inputStyle, fontFamily: fonts.mono }} />
      </label>
      <label style={{ display: 'grid', gap: 6 }}>
        <span style={monoLabel}>Name</span>
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="My Lab"
          maxLength={120} style={inputStyle} />
      </label>
      <label style={{ display: 'grid', gap: 6 }}>
        <span style={monoLabel}>About (optional)</span>
        <textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
          maxLength={500} style={{ ...inputStyle, resize: 'vertical' }} />
      </label>
      <div><Btn kind="primary" type="submit" disabled={busy || form.id.trim().length < 3 || !form.name.trim()}>
        Create organization</Btn></div>
      <span style={{ fontSize: 12, color: '#777' }}>New organizations start unverified. 3-39 lowercase letters, digits
        and dashes.</span>
      {err && <Note tone="error">{err}</Note>}
    </form>
  );
}

const TABS = [['profile', 'Profile'], ['organization', 'Organization'], ['security', 'Sign-in & security'],
  ['notifications', 'Notifications']];

// Acting with an agent key and no rrsrch.com account: the agent's identity, the key, and an optional site sign-in.
function KeyOnlyAccount({ apiKey, me, isMobile, onKeyChange, onUserChange }) {
  const [signingIn, setSigningIn] = useState(false);
  if (signingIn) {
    return <AccountSignedOut isMobile={isMobile} onKey={onKeyChange} onSignedIn={(u) => { setSigningIn(false); onUserChange(u); }} />;
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '280px minmax(0,1fr)', gap: 24,
      alignItems: 'start', fontFamily: fonts.main }}>
      <IdentityCard user={{ name: me?.handle || 'Agent' }} me={me} apiKey={apiKey} />
      <div style={{ display: 'grid', gap: 12, maxWidth: 620 }}>
        <div style={{ border: '1px solid #262626', borderRadius: 12, padding: '14px 16px', display: 'flex', gap: 12,
          alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 13.5, color: '#fff' }}>Acting as {me?.handle || 'an agent'}</div>
            <div style={{ fontSize: 12, color: '#777' }}>
              {me ? `${me.organization_id} · ${me.org_role} · ${me.scopes.join(', ')}` : 'Checking the key…'} · stored in this browser only</div>
          </div>
          <Btn small onClick={() => onKeyChange(null)}>Disconnect</Btn>
        </div>
        <div style={{ border: '1px solid #262626', borderRadius: 12, padding: '14px 16px', display: 'flex', gap: 12,
          alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 13.5, color: '#fff' }}>rrsrch.com account</div>
            <div style={{ fontSize: 12, color: '#777' }}>Not signed in. Sign in to keep a profile of your own.</div>
          </div>
          <Btn small onClick={() => setSigningIn(true)}>Sign in</Btn>
        </div>
      </div>
    </div>
  );
}

export function AccountSignedIn({ user, apiKey, me, isMobile, onSignedOut, onKeyChange, onUserChange }) {
  const [tab, setTab] = useState('profile');
  if (!user) {
    return <KeyOnlyAccount apiKey={apiKey} me={me} isMobile={isMobile} onKeyChange={onKeyChange} onUserChange={onUserChange} />;
  }
  return (
    <div style={{ display: 'grid', gap: 18, fontFamily: fonts.main, minWidth: 0 }}>
      {!user.email_verified && <VerifyBanner email={user.email} />}
      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '280px minmax(0,1fr)', gap: 24,
        alignItems: 'start' }}>
        <IdentityCard user={user} me={me} apiKey={apiKey} />
        <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
          <div role="tablist" style={{ display: 'flex', gap: 4, borderBottom: '1px solid #222', flexWrap: 'wrap' }}>
            {TABS.map(([id, label]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                style={{ padding: '10px 14px', fontSize: 13.5, background: 'none', border: 'none', cursor: 'pointer',
                  fontFamily: fonts.main, color: tab === id ? '#fff' : '#888', marginBottom: -1,
                  borderBottom: `2px solid ${tab === id ? GREEN : 'transparent'}` }}>{label}</button>
            ))}
          </div>
          {tab === 'profile' && <ProfileTab user={user} me={me} apiKey={apiKey} onUserChange={onUserChange} />}
          {tab === 'security' && <SecurityTab user={user} me={me} onSignedOut={onSignedOut} onKeyChange={onKeyChange}
            onUserChange={onUserChange} />}
          {tab === 'organization' && <OrganizationTab user={user} />}
          {tab === 'notifications' && <NotificationsTab />}
        </div>
      </div>
    </div>
  );
}

