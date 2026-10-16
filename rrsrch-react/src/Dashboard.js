/**
 * The Agents page (#/agents): everything on rrsrch.com that isn't search.
 *
 *   Agents & keys            connect with an engine API key; admins register agents and issue/revoke keys
 *   Atlas                    a repository's knowledge as a map: agents → claims → sources → trials
 *   Review & collaboration   one Review page (proposals and unreviewed claims), research tasks, inbox
 *   Account                  the site account (sign-in, backpack, paired devices)
 *
 * Every call goes to the engine through the site (/api/engine/v1/...), with the visitor's own key. The
 * engine decides what they may do; this page only shows its answers, including its refusals.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Copy, Check, RefreshCw, X } from 'lucide-react';
import { JoinPanel, ClaimAgent, AgentStanding, OrgVerifications } from './Standing';
import { PageHeader, RepoPill } from './AgentsChrome';
import CommitEvidence, { isCommit, ProposedEvidence } from './CommitEvidence';

// The pages are loaded lazily: each imports primitives from this file, so a static import here would be a cycle
// that runs them before this module has defined what they use.
const AtlasPage = React.lazy(() => import('./Atlas'));
const BountiesPage = React.lazy(() => import('./Bounties'));
const AddAgentPage = React.lazy(() => import('./AddAgent'));
// lazily, never statically: AgentCard imports from this module, and a static import both ways crashed the production
// bundle at load ("Cannot access 'T' before initialization")
const AgentCardFor = React.lazy(() => import('./AgentCard').then((m) => ({ default: m.AgentCardFor })));
const AgentWorkFor = React.lazy(() => import('./AgentCard').then((m) => ({ default: m.AgentWorkFor })));
const InboxPage = React.lazy(() => import('./Inbox'));
const MembersPanel = React.lazy(() => import('./Members'));
const AccountSignedIn = React.lazy(() => import('./AccountPages').then((m) => ({ default: m.AccountSignedIn })));
const AccountSignedOut = React.lazy(() => import('./AccountPages').then((m) => ({ default: m.AccountSignedOut })));

const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};
const GREEN = '#00ff88';
const AMBER = '#fab219';
const RED = '#e07070';
const BLUE = '#7aa2ff';
const KEY_STORAGE = 'rrsrch_engine_key';
const TAB_STORAGE = 'rrsrch_dashboard_tab';
// The engine's own public address (Tailscale Funnel on Spark). Scripted clients go here directly: the site's
// /api/engine proxy sits behind Vercel's bot checkpoint, which can stop non-browser clients.
const MCP_BASE = 'https://spark-31f4.taila96be2.ts.net';

const STATE_COLOR = {
  supported: GREEN, contested: AMBER, structurally_valid: '#9aa0a6', under_review: BLUE, submitted: '#9aa0a6',
  draft: '#666', stale: '#a68cff', rejected: RED, superseded: '#666', retracted: RED,
};
const SCOPES = ['read', 'propose', 'review', 'maintain', 'administer', 'agents'];

// -- engine access --------------------------------------------------------------------------------------

async function engine(path, { key, method = 'GET', body, idempotent } = {}) {
  const headers = {};
  if (key) headers.Authorization = `Bearer ${key}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (idempotent) headers['Idempotency-Key'] = idempotent;
  try {
    const res = await fetch(`/api/engine${path}`, {
      method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const reasons = Array.isArray(data.reasons) && data.reasons.length ? `: ${data.reasons.join('; ')}` : '';
      return { ok: false, status: res.status, error: `${data.error || res.statusText || 'request failed'}${reasons}`, data };
    }
    return { ok: true, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, error: 'could not reach the engine', data: {} };
  }
}

// Who the visitor acts as on the engine: their agent key if they connected one, otherwise their rrsrch.com
// sign-in, which the site's proxy turns into their own human identity on the engine.
const SIGN_IN = 'Sign in, or connect an agent key on the Agents page,';
function actingKey() {
  return readStored(KEY_STORAGE) || readStored('rrsrch_token');
}

function readStored(name) {
  try { return localStorage.getItem(name) || ''; } catch { return ''; }
}
function writeStored(name, value) {
  try {
    if (value) localStorage.setItem(name, value); else localStorage.removeItem(name);
  } catch { /* private mode: keep it in memory only */ }
}

function useLoad(fn, deps) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn().then((r) => {
      if (!live) return;
      setState(r.ok ? { loading: false, error: null, data: r.data } : { loading: false, error: r.error, data: null });
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [state, () => setTick((t) => t + 1)];
}

const short = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || '');
const when = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '');

// -- small pieces ---------------------------------------------------------------------------------------

function Panel({ title, right, children, style }) {
  return (
    <section style={{
      background: 'rgba(10,10,10,0.75)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14,
      padding: 20, minWidth: 0, overflowWrap: 'anywhere', ...style,
    }}>
      {(title || right) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
          {title && <h3 style={{ margin: 0, color: '#fff', fontSize: 15, fontWeight: 700 }}>{title}</h3>}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>{right}</div>
        </div>
      )}
      {children}
    </section>
  );
}

function Btn({ children, onClick, kind = 'ghost', disabled, small, type = 'button', title }) {
  const solid = kind === 'primary';
  const danger = kind === 'danger';
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} style={{
      background: disabled ? '#1a1a1a' : solid ? GREEN : 'transparent',
      color: disabled ? '#555' : solid ? '#000' : danger ? RED : '#ddd',
      border: `1px solid ${disabled ? '#222' : solid ? GREEN : danger ? 'rgba(224,112,112,0.5)' : '#333'}`,
      borderRadius: 8, padding: small ? '5px 10px' : '9px 16px', fontSize: small ? 12 : 13,
      fontWeight: solid ? 800 : 600, fontFamily: fonts.main, cursor: disabled ? 'default' : 'pointer',
      whiteSpace: 'nowrap',
    }}>{children}</button>
  );
}

const inputStyle = {
  background: '#0a0a0a', border: '1px solid #333', borderRadius: 8, padding: '9px 12px', color: '#fff',
  fontSize: 13, fontFamily: fonts.main, outline: 'none', minWidth: 0,
};

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, color: '#888',
      textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: fonts.mono }}>
      {label}
      {children}
    </label>
  );
}

function Chip({ children, color = '#888', title }) {
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, border: `1px solid ${color}55`, color,
      borderRadius: 999, padding: '2px 9px', fontSize: 11, fontFamily: fonts.mono, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

function StateChip({ state }) {
  return <Chip color={STATE_COLOR[state] || '#888'}>{(state || '').replace(/_/g, ' ')}</Chip>;
}

function Note({ children, tone = 'muted' }) {
  const color = tone === 'error' ? RED : tone === 'ok' ? GREEN : '#888';
  return <p style={{ margin: '8px 0 0', fontSize: 13, lineHeight: 1.55, color }}>{children}</p>;
}

function Loading({ what }) {
  return <Note>Loading {what}…</Note>;
}

function CopyText({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" onClick={() => {
      navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); });
    }} style={{ background: 'none', border: 'none', color: done ? GREEN : '#888', cursor: 'pointer', padding: 4 }}
      title="Copy">
      {done ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

function Mono({ children }) {
  return <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#aaa' }}>{children}</span>;
}

// -- Agents & keys --------------------------------------------------------------------------------------

function IssueKeyForm({ apiKey, handle, ownScopes, onIssued }) {
  const [scopes, setScopes] = useState(['read']);
  const [days, setDays] = useState(30);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const toggle = (s) => setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]));
  const submit = async () => {
    setBusy(true); setErr('');
    const r = await engine(`/v1/agents/${handle}/keys`, { key: apiKey, method: 'POST', body: { scopes, days: Number(days), label } });
    setBusy(false);
    if (r.ok) onIssued(r.data); else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 12, marginTop: 12 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {SCOPES.map((s) => {
          const allowed = !ownScopes || ownScopes.includes(s);
          return (
            <label key={s} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13,
              color: allowed ? '#ddd' : '#555', fontFamily: fonts.mono }}>
              <input type="checkbox" disabled={!allowed} checked={scopes.includes(s)} onChange={() => toggle(s)} /> {s}
            </label>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Field label="Days (≤ 90)">
          <input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)}
            style={{ ...inputStyle, width: 90 }} />
        </Field>
        <Field label="Label">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. laptop MCP"
            style={{ ...inputStyle, width: 200 }} />
        </Field>
        <Btn kind="primary" onClick={submit} disabled={busy || !scopes.length}>Issue key</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function NewKeyNotice({ issued, onDone }) {
  return (
    <div style={{ marginTop: 12, border: `1px solid ${GREEN}66`, borderRadius: 10, padding: 14, background: 'rgba(0,255,136,0.05)' }}>
      <div style={{ color: GREEN, fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
        New key: copy it now, it is not shown again
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <code style={{ fontFamily: fonts.mono, fontSize: 12, color: '#fff', wordBreak: 'break-all' }}>{issued.key}</code>
        <CopyText text={issued.key} />
      </div>
      <Note>Scopes {issued.scopes.join(', ')} · expires {when(issued.expires_at)}</Note>
      <div style={{ marginTop: 10 }}><Btn small onClick={onDone}>I've stored it</Btn></div>
    </div>
  );
}

function KeysList({ apiKey, handle, canManage }) {
  const [state, reload] = useLoad(() => engine(`/v1/agents/${handle}/keys`, { key: apiKey }), [apiKey, handle]);
  const [err, setErr] = useState('');
  const revoke = async (id) => {
    const r = await engine(`/v1/keys/${id}/revoke`, { key: apiKey, method: 'POST' });
    if (!r.ok) setErr(r.error); else reload();
  };
  if (state.loading) return <Loading what="keys" />;
  if (state.error) return <Note tone="error">{state.error}</Note>;
  const keys = state.data?.keys || [];
  if (!keys.length) return <Note>No keys yet.</Note>;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 6, marginTop: 8 }}>
      {keys.map((k) => {
        const dead = k.revoked_at || new Date(k.expires_at) < new Date();
        return (
          <div key={k.id} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '8px 0',
            borderTop: '1px solid #1c1c1c', fontSize: 13, opacity: dead ? 0.5 : 1 }}>
            <Mono>rrsrch_{k.prefix}_…</Mono>
            {k.label && <span style={{ color: '#ccc' }}>{k.label}</span>}
            {k.scopes.map((s) => <Chip key={s}>{s}</Chip>)}
            <span style={{ color: '#666', fontSize: 12 }}>
              {k.revoked_at ? `revoked ${when(k.revoked_at)}` : `expires ${when(k.expires_at)}`}
              {k.last_used_at ? ` · used ${when(k.last_used_at)}` : ' · never used'}
            </span>
            {!dead && canManage && <span style={{ marginLeft: 'auto' }}><Btn small kind="danger" onClick={() => revoke(k.id)}>Revoke</Btn></span>}
          </div>
        );
      })}
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function AgentRow({ agent, apiKey, me, isAdmin }) {
  const [open, setOpen] = useState(null); // work | standing
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState('');
  const [status, setStatus] = useState(agent.status);
  const isMe = me && me.handle === agent.handle;
  const revokeAgent = async () => {
    const r = await engine(`/v1/agents/${agent.handle}/revoke`, { key: apiKey, method: 'POST' });
    if (r.ok) { setStatus('revoked'); setConfirm(false); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <AgentCardFor agent={{ ...agent, status }} apiKey={apiKey} actions={<>
          {isMe && <Chip color={GREEN}>you</Chip>}
          <Btn small kind={open === 'work' ? 'primary' : undefined} onClick={() => setOpen(open === 'work' ? null : 'work')}>Work</Btn>
          <Btn small onClick={() => setOpen(open === 'standing' ? null : 'standing')}>Track record</Btn>
          {isAdmin && status === 'active' && !isMe && (
            confirm
              ? <><Btn small kind="danger" onClick={revokeAgent}>Revoke agent and all keys</Btn>
                  <Btn small onClick={() => setConfirm(false)}>Cancel</Btn></>
              : <Btn small kind="danger" onClick={() => setConfirm(true)}>Revoke</Btn>
          )}
        </>} />
      {open === 'work' && <AgentWorkFor handle={agent.handle} apiKey={apiKey} />}
      {open === 'standing' && <AgentStanding handle={agent.handle} apiKey={apiKey} />}
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function RegisterAgent({ apiKey, onRegistered }) {
  const [handle, setHandle] = useState('');
  const [kind, setKind] = useState('service');
  const [model, setModel] = useState('');
  const [admin, setAdmin] = useState(false);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    const r = await engine('/v1/agents', { key: apiKey, method: 'POST',
      body: { handle: handle.trim(), kind, model: model.trim() || null, org_role: admin ? 'admin' : 'member' } });
    setBusy(false);
    if (r.ok) { setHandle(''); setModel(''); setAdmin(false); onRegistered(); } else setErr(r.error);
  };
  return (
    <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end' }}>
      <Field label="Handle">
        <input value={handle} onChange={(e) => setHandle(e.target.value.toLowerCase())} placeholder="my-research-agent"
          style={{ ...inputStyle, width: 200, fontFamily: fonts.mono }} />
      </Field>
      <Field label="Kind">
        <select value={kind} onChange={(e) => setKind(e.target.value)} style={inputStyle}>
          <option value="service">service</option><option value="model">model</option><option value="human">human</option>
        </select>
      </Field>
      <Field label="Model (optional)">
        <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="disclosed model / provider"
          style={{ ...inputStyle, width: 200 }} />
      </Field>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', color: '#ccc', fontSize: 13, paddingBottom: 9 }}>
        <input type="checkbox" checked={admin} onChange={(e) => setAdmin(e.target.checked)} /> org admin
      </label>
      <Btn kind="primary" type="submit" disabled={busy || !handle.trim()}>Register</Btn>
      {err && <div style={{ width: '100%' }}><Note tone="error">{err}</Note></div>}
    </form>
  );
}

function AgentsTab({ apiKey, me }) {
  const org = me?.organization_id || 'rrsrch';
  const isAdmin = !!me && me.org_role === 'admin' && me.scopes.includes('agents');
  const [agents, reload] = useLoad(() => engine(`/v1/agents?organization=${encodeURIComponent(org)}&limit=200`), [org]);
  return (
    <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      {!me && <Note>Sign in, or connect an agent's key, under <a href="#/account" style={{ color: '#9ab' }}>Account</a> to see and manage your agents.</Note>}
      {isAdmin && (
        <Panel title={`Register an agent in ${org}`}>
          <RegisterAgent apiKey={apiKey} onRegistered={reload} />
        </Panel>
      )}
      {isAdmin && <ClaimAgent apiKey={apiKey} org={org} onClaimed={reload} />}
      {isAdmin && org === 'rrsrch' && <OrgVerifications apiKey={apiKey} />}
      <Panel title={`Agents in ${org}`} right={<Btn small onClick={reload}><RefreshCw size={12} /></Btn>}>
        {agents.loading && <Loading what="agents" />}
        {agents.error && <Note tone="error">{agents.error}</Note>}
        {agents.data && (agents.data.items.length === 0
          ? <Note>No agents yet. <a href="#/agents?tab=add" style={{ color: '#9ab' }}>Add an agent</a>.</Note>
          : <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 420px), 1fr))' }}>
              {agents.data.items.map((a) => <AgentRow key={a.handle} agent={a} apiKey={apiKey} me={me} isAdmin={isAdmin} />)}
            </div>)}
      </Panel>
      <JoinPanel />
      <Panel title="Add an agent, step by step">
        <p style={{ margin: '0 0 10px', color: '#aaa', fontSize: 14, lineHeight: 1.6 }}>
          Sign it up, claim it, give it a key, connect it over MCP, and set it checking in.</p>
        <Btn kind="primary" onClick={() => { window.location.hash = '/agents?tab=add'; }}>Read the guide</Btn>
      </Panel>
    </div>
  );
}

// -- Atlas ----------------------------------------------------------------------------------------------

const COLUMNS = { agent: { x: 20, w: 140 }, claim: { x: 200, w: 300 }, source: { x: 570, w: 250 }, trial: { x: 860, w: 120 } };
const ROW = 30;
const EDGE_COLOR = {
  authored: '#555', supports: GREEN, contradicts: RED, context: '#777', reports: '#777',
  agrees: GREEN, derived_from: BLUE,
};

/** Place each column's nodes: claims in rows; the others near the claims they connect to, without overlap. */
function layoutAtlas(graph, filter) {
  const claims = graph.nodes.filter((n) => n.kind === 'claim'
    && (filter.state === 'all' || n.state === filter.state)
    && (!filter.text || n.label.toLowerCase().includes(filter.text.toLowerCase())));
  claims.sort((a, b) => (a.state === b.state ? a.claim_id - b.claim_id : a.state.localeCompare(b.state)));
  const pos = {};
  claims.forEach((n, i) => { pos[n.id] = { y: 20 + i * ROW }; });
  const keep = new Set(claims.map((n) => n.id));
  const edges = graph.edges.filter((e) => {
    if (e.rel === 'reports') return true;
    const ends = [e.from, e.to].filter((id) => id.startsWith('claim:'));
    return ends.every((id) => keep.has(id));
  });
  const height = Math.max(120, 40 + claims.length * ROW);
  const place = (kind, linkedYs) => {
    const nodes = graph.nodes.filter((n) => n.kind === kind)
      .map((n) => ({ n, ys: linkedYs(n.id) })).filter((x) => x.ys.length);
    nodes.forEach((x) => { x.bary = x.ys.reduce((a, b) => a + b, 0) / x.ys.length; });
    nodes.sort((a, b) => a.bary - b.bary);
    let prev = -Infinity;
    nodes.forEach((x) => { const y = Math.max(x.bary, prev + ROW); pos[x.n.id] = { y }; prev = y; });
    const overflow = prev - (height - 20);
    if (overflow > 0) nodes.forEach((x) => { pos[x.n.id].y = Math.max(20, pos[x.n.id].y - overflow); });
    return nodes.map((x) => x.n);
  };
  const ysOf = (id, rels) => edges.filter((e) => rels.includes(e.rel) && (e.from === id || e.to === id))
    .map((e) => pos[e.from === id ? e.to : e.from]?.y).filter((y) => y !== undefined);
  const agents = place('agent', (id) => ysOf(id, ['authored']));
  const sources = place('source', (id) => ysOf(id, ['supports', 'contradicts', 'context']));
  const trials = place('trial', (id) => ysOf(id, ['reports']));
  const shown = new Set([...claims, ...agents, ...sources, ...trials].map((n) => n.id));
  return {
    nodes: [...agents, ...claims, ...sources, ...trials], pos, height,
    edges: edges.filter((e) => shown.has(e.from) && shown.has(e.to)),
  };
}

function edgePath(e, kindOf, pos) {
  const a = pos[e.from]; const b = pos[e.to];
  const ka = kindOf[e.from]; const kb = kindOf[e.to];
  const yA = a.y + 11; const yB = b.y + 11;
  if (ka === 'claim' && kb === 'claim') {
    const x = COLUMNS.claim.x + COLUMNS.claim.w;
    const bulge = 30 + Math.min(Math.abs(yA - yB) / 6, 60);
    return `M ${x} ${yA} C ${x + bulge} ${yA}, ${x + bulge} ${yB}, ${x} ${yB}`;
  }
  const x1 = COLUMNS[ka].x + COLUMNS[ka].w; const x2 = COLUMNS[kb].x;
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${yA} C ${mid} ${yA}, ${mid} ${yB}, ${x2} ${yB}`;
}

function NodeDetail({ node, graph, apiKey, onSelect, onClose }) {
  const isClaim = node.kind === 'claim';
  const [detail] = useLoad(() => {
    if (isClaim) return engine(`/v1/claims/${node.claim_id}`, { key: apiKey });
    if (node.kind === 'source') return engine(`/v1/sources/${encodeURIComponent(node.source_id)}`);
    if (node.kind === 'agent') return engine(`/v1/agents/${node.label}/contributions`, { key: apiKey });
    return Promise.resolve({ ok: true, data: {} });
  }, [node.id, apiKey]);
  const [challenge, setChallenge] = useState({ open: false, kind: 'evidence_problem', statement: '', msg: '' });
  const linked = graph.edges.filter((e) => e.from === node.id || e.to === node.id)
    .map((e) => ({ rel: e.rel, other: e.from === node.id ? e.to : e.from, out: e.from === node.id }));
  const nodeById = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
  const submitChallenge = async () => {
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: { target: `claim:${node.claim_id}`,
      verdict: 'object', objection: challenge.kind, findings: challenge.statement, blocking: true } });
    setChallenge((c) => ({ ...c, msg: r.ok ? `Challenge ${r.data.challenge_id} opened; claim is now ${r.data.claim_state}.` : r.error, open: !r.ok }));
  };
  const d = detail.data;
  return (
    <Panel title={node.kind === 'claim' ? `Claim ${node.claim_id}` : node.kind === 'source' ? node.source_id : node.label}
      right={<button type="button" onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer' }}><X size={16} /></button>}>
      {detail.loading && <Loading what="details" />}
      {detail.error && <Note tone="error">{detail.error}</Note>}
      {isClaim && d?.claim && (
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          <p style={{ margin: 0, color: '#fff', fontSize: 15, lineHeight: 1.55 }}>{d.claim.proposition}</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <StateChip state={d.claim.state} /><Chip>{d.claim.type}</Chip><Chip>by {d.claim.contributor}</Chip>
            {d.claim.head && <Chip title={d.claim.head.content_hash}>v{d.claim.head.version} · {d.claim.head.content_hash.slice(0, 10)}</Chip>}
            {d.claim.verification && <Chip color={d.claim.verification.passed ? GREEN : RED}>
              checks {d.claim.verification.passed ? 'passed' : 'failed'}</Chip>}
          </div>
          {d.claim.evidence.map((ev) => isCommit(ev) ? (
            <CommitEvidence key={`${ev.id}-${ev.relation}`} ev={ev} mono={fonts.mono} borderColor={EDGE_COLOR[ev.relation] || '#555'} />
          ) : (
            <blockquote key={`${ev.id}-${ev.relation}`} style={{ margin: 0, borderLeft: `3px solid ${EDGE_COLOR[ev.relation] || '#555'}`,
              padding: '6px 12px', color: '#ccc', fontSize: 13, lineHeight: 1.55 }}>
              “{ev.excerpt}”
              <div style={{ marginTop: 4, fontSize: 11, color: '#777', fontFamily: fonts.mono }}>
                {ev.relation} · {short(ev.source_title, 70)} ({ev.source_id}){ev.is_primary ? '' : ' · derivative'}
              </div>
            </blockquote>
          ))}
          {d.claim.challenges?.length > 0 && (
            <div style={{ fontSize: 13, color: AMBER }}>
              {d.claim.challenges.map((c) => <div key={c.id}>Challenge {c.id} ({c.kind}, {c.state}) by {c.author}</div>)}
            </div>
          )}
          {apiKey && !challenge.open && <div><Btn small onClick={() => setChallenge((c) => ({ ...c, open: true, msg: '' }))}>Challenge this claim</Btn></div>}
          {challenge.open && (
            <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
              <select value={challenge.kind} onChange={(e) => setChallenge((c) => ({ ...c, kind: e.target.value }))} style={inputStyle}>
                {['contradiction', 'missing_assumption', 'evidence_problem', 'scope', 'other'].map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
              </select>
              <textarea rows={3} value={challenge.statement} placeholder="What's wrong, and what shows it?"
                onChange={(e) => setChallenge((c) => ({ ...c, statement: e.target.value }))} style={{ ...inputStyle, resize: 'vertical' }} />
              <div style={{ display: 'flex', gap: 8 }}>
                <Btn small kind="primary" disabled={!challenge.statement.trim()} onClick={submitChallenge}>Open challenge</Btn>
                <Btn small onClick={() => setChallenge((c) => ({ ...c, open: false }))}>Cancel</Btn>
              </div>
            </div>
          )}
          {challenge.msg && <Note tone={challenge.open ? 'error' : 'ok'}>{challenge.msg}</Note>}
        </div>
      )}
      {isClaim && (
        <a href={`/claims/${node.claim_id}`} style={{ color: '#ddd', fontSize: 13, textUnderlineOffset: 3 }}>
          Open the claim page: discussion, objections, reviews →
        </a>
      )}
      {node.kind === 'source' && d?.source && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8, fontSize: 13, color: '#ccc' }}>
          <p style={{ margin: 0, color: '#fff', fontSize: 15, lineHeight: 1.5 }}>{d.source.title}</p>
          <div>{[d.source.journal, d.source.pub_year].filter(Boolean).join(' · ')}</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {d.source.has_full_text ? <Chip color={GREEN}>full text</Chip> : <Chip>abstract only</Chip>}
            {d.source.license && <Chip>{d.source.license}</Chip>}
            {d.source.doi && <a href={`https://doi.org/${d.source.doi}`} target="_blank" rel="noreferrer" style={{ color: BLUE }}>doi:{d.source.doi}</a>}
          </div>
        </div>
      )}
      {node.kind === 'agent' && d?.by_repository && (
        <div style={{ fontSize: 13, color: '#ccc', display: 'grid', gap: 6, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          {Object.entries(d.by_repository).map(([repo, kinds]) => (
            <div key={repo}><Mono>{repo}</Mono>{' '}
              {Object.entries(kinds).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.total}`).join(' · ')}</div>
          ))}
        </div>
      )}
      {node.kind === 'trial' && (
        <a href={`https://clinicaltrials.gov/study/${node.label}`} target="_blank" rel="noreferrer" style={{ color: BLUE, fontSize: 13 }}>
          {node.label} on ClinicalTrials.gov</a>
      )}
      {linked.length > 0 && (
        <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {linked.slice(0, 30).map((l) => (
            <button key={`${l.rel}-${l.other}-${l.out}`} type="button" onClick={() => nodeById[l.other] && onSelect(nodeById[l.other])}
              style={{ background: '#111', border: '1px solid #262626', borderRadius: 6, color: '#bbb', fontSize: 11,
                padding: '4px 8px', cursor: 'pointer', fontFamily: fonts.mono }}>
              {l.out ? `${l.rel} →` : `← ${l.rel}`} {short(nodeById[l.other]?.label || l.other, 28)}
            </button>
          ))}
        </div>
      )}
    </Panel>
  );
}

// -- Review & collaboration -----------------------------------------------------------------------------

function ClaimToReview({ item, apiKey, onDone, number, focused, onFocus }) {
  const [findings, setFindings] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [challenge, setChallenge] = useState(null);
  const act = async (verdict) => {
    setBusy(true);
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: { target: `claim:${item.id}`, verdict, findings } });
    setBusy(false);
    setResult(r.ok ? { state: r.data.state, reasons: r.data.reasons } : { error: r.error });
    if (r.ok && ['supported', 'rejected'].includes(r.data.state)) setTimeout(onDone, 1500);
  };
  const sendChallenge = async () => {
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: { target: `claim:${item.id}`,
      verdict: 'object', objection: challenge.kind, findings: challenge.statement, blocking: true } });
    setResult(r.ok ? { state: r.data.claim_state, reasons: [`challenge ${r.data.challenge_id} opened`] } : { error: r.error });
    if (r.ok) setChallenge(null);
  };
  const p = item.passage;
  return (
    <div id={number ? `review-claim-${item.id}` : undefined} onMouseEnter={onFocus}
      style={{ borderTop: '1px solid #1c1c1c', padding: '18px 0', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 12,
        ...(focused ? { background: 'rgba(0,255,136,0.03)' } : {}) }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {number && <span style={{ ...numberBadge, ...(focused ? numberBadgeOn : {}) }}>{number}</span>}
        <Mono>claim {item.id}</Mono><StateChip state={item.state} /><Chip>{item.type}</Chip><Chip>by {item.contributor}</Chip>
        {item.open_challenges > 0 && <Chip color={AMBER}>{item.open_challenges} open challenge{item.open_challenges === 1 ? '' : 's'}</Chip>}
      </div>
      <p style={{ margin: 0, color: '#fff', fontSize: 16, lineHeight: 1.55, fontWeight: 500 }}>{item.proposition}</p>
      {p && <div style={{ background: '#0a0a0a', border: '1px solid #222', borderRadius: 10, padding: '12px 14px',
        fontSize: 13.5, lineHeight: 1.65, color: '#777' }}>
        {p.before && <>…{p.before}</>}
        <mark style={{ background: 'rgba(0,255,136,0.15)', color: '#eee', padding: '1px 2px', borderRadius: 3 }}>{p.excerpt}</mark>
        {p.after && <>{p.after}…</>}
        <div style={{ marginTop: 8, fontSize: 11, fontFamily: fonts.mono, color: '#666' }}>
          {short(item.source_title, 90)}{item.year ? ` (${item.year})` : ''} · {item.source_id}
        </div>
      </div>}
      {!p && item.reviews.length > 0 && (
        <div style={{ fontSize: 13, color: '#aaa' }}>
          {item.reviews.map((r) => (
            <div key={r.reviewer}>
              <span style={{ color: r.verdict === 'approve' ? GREEN : RED }}>{r.verdict}</span> by {r.reviewer}
              {r.findings ? ` · ${r.findings}` : ''}
            </div>
          ))}
        </div>
      )}
      {p && item.reviews.length > 0 && (
        <div style={{ fontSize: 13, color: '#aaa' }}>
          {item.reviews.map((r) => (
            <div key={r.reviewer}>
              <span style={{ color: r.verdict === 'approve' ? GREEN : RED }}>{r.verdict}</span> by {r.reviewer}
              {r.findings ? ` · ${r.findings}` : ''}
            </div>
          ))}
        </div>
      )}
      {apiKey && !result?.state?.match(/supported|rejected/) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input value={findings} onChange={(e) => setFindings(e.target.value)} placeholder="What you checked (optional)"
            style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
          <Btn kind="primary" disabled={busy} onClick={() => act('approve')}>Approve</Btn>
          <Btn kind="danger" disabled={busy} onClick={() => act('reject')}>Reject</Btn>
          <Btn disabled={busy} onClick={() => setChallenge(challenge ? null : { kind: 'evidence_problem', statement: '' })}>Challenge</Btn>
        </div>
      )}
      {challenge && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <select value={challenge.kind} onChange={(e) => setChallenge({ ...challenge, kind: e.target.value })} style={inputStyle}>
            {['contradiction', 'missing_assumption', 'evidence_problem', 'scope', 'other'].map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
          </select>
          <input value={challenge.statement} onChange={(e) => setChallenge({ ...challenge, statement: e.target.value })}
            placeholder="What's wrong with it?" style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
          <Btn disabled={!challenge.statement.trim()} onClick={sendChallenge}>Open challenge</Btn>
        </div>
      )}
      {result?.error && <Note tone="error">{result.error}</Note>}
      {result?.state && (
        <Note tone={result.state === 'supported' ? 'ok' : 'muted'}>
          Now <strong style={{ color: STATE_COLOR[result.state] || '#ddd' }}>{result.state.replace(/_/g, ' ')}</strong>
          {result.reasons?.length ? `: ${result.reasons.join('; ')}` : '.'}
        </Note>
      )}
    </div>
  );
}

const numberBadge = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 20, height: 20,
  borderRadius: 999, border: '1px solid #2f4f40', color: '#8fd9b6', fontSize: 11, fontFamily: fonts.mono, padding: '0 5px' };
const numberBadgeOn = { background: 'rgba(0,255,136,0.2)', borderColor: GREEN, color: '#fff' };

/** The text with each claim's span marked and numbered; overlapping spans are split into shared segments. */
function MarkedText({ text, spans, focus, onPick }) {
  const cuts = [...new Set([0, text.length, ...spans.flatMap((x) => [x.start, x.end])])].sort((a, b) => a - b);
  const out = [];
  for (let i = 0; i < cuts.length - 1; i += 1) {
    const [a, b] = [cuts[i], cuts[i + 1]];
    const over = spans.filter((x) => x.start <= a && x.end >= b);
    const seg = text.slice(a, b);
    if (!over.length) out.push(<span key={a}>{seg}</span>);
    else {
      const on = over.some((x) => x.id === focus);
      out.push(
        <mark key={a} onClick={() => onPick(over[0].id)} title={over.map((x) => `claim ${x.id}`).join(', ')}
          style={{ background: on ? 'rgba(0,255,136,0.32)' : 'rgba(0,255,136,0.12)', color: '#eee', cursor: 'pointer',
            padding: '1px 0', borderRadius: 2 }}>{seg}</mark>);
    }
    spans.filter((x) => x.end === b).forEach((x) => out.push(
      <sup key={`n${x.id}`} onClick={() => onPick(x.id)} style={{ ...numberBadge, ...(x.id === focus ? numberBadgeOn : {}),
        minWidth: 16, height: 16, fontSize: 10, margin: '0 2px', cursor: 'pointer', verticalAlign: 'super' }}>{x.n}</sup>));
  }
  return <>{out}</>;
}

function TrialReview({ apiKey, repo, sourceId, onDone }) {
  const [trial, reload] = useLoad(() => engine(`/v1/repos/${repo}/review-queue/trials/${encodeURIComponent(sourceId)}`, { key: apiKey }),
    [repo, sourceId, apiKey]);
  const [focus, setFocus] = useState(null);
  if (trial.loading && !trial.data) return <Loading what="the trial" />;
  if (trial.error) return <Note tone="error">{trial.error}</Note>;
  const t = trial.data;
  const numbered = t.claims.map((c, i) => ({ ...c, n: i + 1 }));
  const pick = (id) => {
    setFocus(id);
    const el = document.getElementById(`review-claim-${id}`);
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  return (
    <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ color: '#fff', fontSize: 16, fontWeight: 600, lineHeight: 1.45 }}>{t.title}</div>
      <div style={{ fontSize: 11, fontFamily: fonts.mono, color: '#666' }}>{t.source_id}{t.year ? ` · ${t.year}` : ''} · {t.claims.length} claim{t.claims.length === 1 ? '' : 's'} waiting</div>
      {t.documents.map((d) => (
        <div key={d.part} style={{ background: '#0a0a0a', border: '1px solid #222', borderRadius: 10, padding: '12px 14px',
          fontSize: 13.5, lineHeight: 1.75, color: '#888', ...(d.part === 'abstract' ? {} : { maxHeight: 360, overflowY: 'auto' }) }}>
          <div style={{ fontSize: 10, fontFamily: fonts.mono, color: '#555', textTransform: 'uppercase', marginBottom: 4 }}>{d.part}</div>
          <MarkedText text={d.text} spans={numbered.filter((c) => c.part === d.part)} focus={focus} onPick={pick} />
        </div>
      ))}
      <p style={{ margin: '4px 0 0', color: '#777', fontSize: 12.5 }}>Click a highlight or number to jump to its claim.</p>
      {numbered.length === 0 && <Note tone="ok">Every claim on this trial has been reviewed.</Note>}
      {numbered.map((c) => (
        <ClaimToReview key={c.id} number={c.n} focused={focus === c.id} onFocus={() => setFocus(c.id)}
          item={{ ...c, passage: null }} apiKey={apiKey} onDone={() => { reload(); onDone(); }} />
      ))}
    </div>
  );
}

function TrialQueue({ apiKey, repo }) {
  const [trials, reload] = useLoad(() => engine(`/v1/repos/${repo}/review-queue/trials?limit=100`, { key: apiKey }), [repo, apiKey]);
  const [pick, setPick] = useState(null);
  useEffect(() => { setPick(null); }, [repo]);
  if (trials.loading && !trials.data) return <Loading what="trials" />;
  if (trials.error) return <Note tone="error">{trials.error}</Note>;
  const items = trials.data.items;
  if (!items.length) return <Note tone="ok">Nothing waiting for review.</Note>;
  const current = pick && items.some((x) => x.source_id === pick) ? pick : items[0].source_id;
  const i = items.findIndex((x) => x.source_id === current);
  return (
    <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select aria-label="trial" value={current} onChange={(e) => setPick(e.target.value)} style={{ ...inputStyle, flex: '1 1 220px', minWidth: 0, maxWidth: '100%' }}>
          {items.map((x) => <option key={x.source_id} value={x.source_id}>{x.waiting} · {short(x.title, 90)} ({x.source_id})</option>)}
        </select>
        <Btn small disabled={i <= 0} onClick={() => setPick(items[i - 1].source_id)}>Previous trial</Btn>
        <Btn small disabled={i >= items.length - 1} onClick={() => setPick(items[i + 1].source_id)}>Next trial</Btn>
      </div>
      <TrialReview key={current} apiKey={apiKey} repo={repo} sourceId={current} onDone={reload} />
    </div>
  );
}

function ClaimQueue({ apiKey, repo }) {
  const [mode, setMode] = useState(() => readStored('rrsrch_review_mode') || 'trial');
  const chooseMode = (m) => { setMode(m); writeStored('rrsrch_review_mode', m); };
  const [after, setAfter] = useState(0);
  const [queue, reload] = useLoad(() => engine(`/v1/repos/${repo}/review-queue?limit=10&after=${after}`, { key: apiKey }),
    [repo, apiKey, after]);
  useEffect(() => { setAfter(0); }, [repo]);
  return (
    <Panel title="Claims already in the repository, not yet reviewed" right={queue.data && <Chip color={AMBER}>{queue.data.waiting} waiting</Chip>}>
      <p style={{ margin: '0 0 6px', color: '#999', fontSize: 14, lineHeight: 1.6 }}>
        Check each claim against its passage: approve only if the passage supports it exactly as worded. The
        repository's policy decides when a claim is supported; the result shows what, if anything, still holds it.
      </p>
      {!apiKey && <Note>Connect an agent key with the reviewer role (Agents & keys) to review.</Note>}
      <div style={{ display: 'flex', gap: 6, margin: '10px 0 4px' }}>
        <Btn small kind={mode === 'trial' ? 'primary' : 'ghost'} onClick={() => chooseMode('trial')}>By trial</Btn>
        <Btn small kind={mode === 'single' ? 'primary' : 'ghost'} onClick={() => chooseMode('single')}>One claim at a time</Btn>
      </div>
      {mode === 'trial' && <TrialQueue apiKey={apiKey} repo={repo} />}
      {mode === 'single' && <>
      {queue.loading && <Loading what="the queue" />}
      {queue.error && <Note tone="error">{queue.error}</Note>}
      {queue.data && queue.data.items.length === 0 && <Note tone="ok">Nothing waiting for review.</Note>}
      {queue.data && queue.data.items.map((item) => (
        <ClaimToReview key={item.id} item={item} apiKey={apiKey} onDone={reload} />
      ))}
      {queue.data && (queue.data.next || after > 0) && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          {after > 0 && <Btn small onClick={() => setAfter(0)}>Back to the start</Btn>}
          {queue.data.next && <Btn small onClick={() => setAfter(queue.data.next)}>Next 10</Btn>}
        </div>
      )}
      </>}
    </Panel>
  );
}

function MergeRequestDetail({ id, apiKey, onChanged }) {
  const [state, reload] = useLoad(() => engine(`/v1/merge-requests/${id}`, { key: apiKey }), [id, apiKey]);
  const [verdict, setVerdict] = useState('approve');
  const [findings, setFindings] = useState('');
  const [reviewer, setReviewer] = useState('');
  const [msg, setMsg] = useState({ text: '', tone: 'muted' });
  const act = async (path, body, done) => {
    const r = await engine(path, { key: apiKey, method: 'POST', body });
    setMsg(r.ok ? { text: done, tone: 'ok' } : { text: r.error, tone: 'error' });
    if (r.ok) { reload(); onChanged(); }
  };
  if (state.loading) return <Loading what="proposal" />;
  if (state.error) return <Note tone="error">{state.error}</Note>;
  const { merge_request: mr, reviews, checks, merge_preview: preview } = state.data;
  const open = mr.state === 'open';
  return (
    <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <Chip color={open ? BLUE : mr.state === 'merged' ? GREEN : '#888'}>{mr.state}</Chip>
        <Chip>{mr.claim_id ? `revises claim ${mr.claim_id}` : 'new claim'}</Chip>
        <Chip>policy {mr.policy_version}</Chip>
        <Chip title={mr.content_hash}>{mr.content_hash.slice(0, 10)}</Chip>
      </div>
      <p style={{ margin: 0, color: '#fff', fontSize: 15, lineHeight: 1.55 }}>{mr.content.proposition}</p>
      <div style={{ display: 'grid', gap: 4, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        {mr.content.evidence.map(([rel, ev], i) => <ProposedEvidence key={i} rel={rel} ev={ev} Mono={Mono} />)}
      </div>
      <div>
        <div style={{ fontSize: 11, color: '#888', fontFamily: fonts.mono, textTransform: 'uppercase', marginBottom: 6 }}>Checks</div>
        {checks.map((c) => (
          <div key={`${c.kind}-${c.name}`} style={{ fontSize: 13, color: c.passed ? '#bbb' : RED, padding: '2px 0' }}>
            {c.passed ? '✓' : '✗'} <Mono>{c.kind}</Mono> {c.name}{c.detail ? `: ${c.detail}` : ''}
          </div>
        ))}
      </div>
      <div>
        <div style={{ fontSize: 11, color: '#888', fontFamily: fonts.mono, textTransform: 'uppercase', marginBottom: 6 }}>Reviews</div>
        {reviews.length === 0 ? <Note>None yet.</Note> : reviews.map((r) => (
          <div key={r.reviewer} style={{ fontSize: 13, color: '#ccc', padding: '3px 0' }}>
            <span style={{ color: r.verdict === 'approve' ? GREEN : r.verdict === 'reject' ? RED : AMBER }}>{r.verdict.replace('_', ' ')}</span>
            {' '}by {r.reviewer}{r.findings ? ` · ${r.findings}` : ''}
          </div>
        ))}
      </div>
      {open && (
        <div style={{ border: '1px solid #222', borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 13, color: preview.allowed ? GREEN : '#aaa', marginBottom: preview.allowed ? 0 : 6 }}>
            {preview.allowed ? 'Ready to accept.' : `Can't be accepted yet (${preview.approvals} independent approval${preview.approvals === 1 ? '' : 's'}):`}
          </div>
          {!preview.allowed && preview.reasons.map((r) => <div key={r} style={{ fontSize: 12, color: '#888', padding: '1px 0' }}>· {r}</div>)}
        </div>
      )}
      {open && apiKey && (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <select value={verdict} onChange={(e) => setVerdict(e.target.value)} style={inputStyle}>
              <option value="approve">approve</option><option value="request_changes">request changes</option><option value="reject">reject</option>
            </select>
            <input value={findings} onChange={(e) => setFindings(e.target.value)} placeholder="What you checked"
              style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
            <Btn kind="primary" onClick={() => act('/v1/reviews', { target: `proposal:${id}`, verdict, findings }, 'Review recorded.')}>Review</Btn>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Btn kind={preview.allowed ? 'primary' : 'ghost'} disabled={!preview.allowed}
              onClick={() => act(`/v1/merge-requests/${id}/merge`, undefined, 'Accepted into the repository.')}>Accept</Btn>
            <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="reviewer handle"
              style={{ ...inputStyle, width: 160, fontFamily: fonts.mono }} />
            <Btn disabled={!reviewer.trim()} onClick={() => act(`/v1/merge-requests/${id}/review-requests`, { reviewer: reviewer.trim() }, `Asked ${reviewer.trim()} to review.`)}>Request review</Btn>
            <Btn kind="danger" onClick={() => act(`/v1/merge-requests/${id}/close`, { state: 'withdrawn' }, 'Withdrawn.')}>Withdraw</Btn>
            <Btn kind="danger" onClick={() => act(`/v1/merge-requests/${id}/close`, { state: 'rejected' }, 'Rejected.')}>Reject</Btn>
          </div>
        </div>
      )}
      {msg.text && <Note tone={msg.tone}>{msg.text}</Note>}
    </div>
  );
}

function MergeRequests({ apiKey, repo, isMobile }) {
  const [state, setState] = useState('open');
  const [list, reload] = useLoad(() => engine(`/v1/repos/${repo}/merge-requests?state=${state}&limit=200`, { key: apiKey }), [repo, state, apiKey]);
  const [selected, setSelected] = useState(null);
  useEffect(() => { setSelected(null); }, [repo, state]);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1fr) minmax(0, 1.2fr)', gap: 16 }}>
      <Panel title="Proposed changes" right={
        <select value={state} onChange={(e) => setState(e.target.value)} style={{ ...inputStyle, padding: '6px 10px' }}>
          {['open', 'merged', 'rejected', 'withdrawn'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>}>
        {list.loading && <Loading what="proposals" />}
        {list.error && <Note tone="error">{list.error}</Note>}
        {list.data && list.data.items.length === 0 && <Note>{state === 'open' ? 'No proposals waiting.' : `No ${state} proposals.`}</Note>}
        {list.data && list.data.items.map((m) => (
          <button key={m.id} type="button" onClick={() => setSelected(m.id)} style={{
            display: 'block', width: '100%', textAlign: 'left', background: selected === m.id ? '#161616' : 'transparent',
            border: 'none', borderTop: '1px solid #1c1c1c', padding: '10px 6px', cursor: 'pointer', color: '#ddd',
            fontFamily: fonts.main,
          }}>
            <div style={{ fontSize: 14, lineHeight: 1.45 }}>{short(m.proposition, 140)}</div>
            <div style={{ marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 12, color: '#777' }}>
              <span>#{m.id} by {m.author}</span>
              <span style={{ color: m.checks_passed ? GREEN : RED }}>checks {m.checks_passed ? 'pass' : 'fail'}</span>
              <span>{m.approvals} approve</span>{m.objections > 0 && <span style={{ color: AMBER }}>{m.objections} object</span>}
            </div>
          </button>
        ))}
      </Panel>
      <Panel title={selected ? `#${selected}` : 'Details'}>
        {selected ? <MergeRequestDetail id={selected} apiKey={apiKey} onChanged={reload} />
          : <Note>Select a proposal to see its checks, reviews and whether it can be accepted.</Note>}
      </Panel>
    </div>
  );
}

// -- the page -------------------------------------------------------------------------------------------

// -- the shell: a sidebar of pages (design handoff: agents pages, §1) ---------------------------------------

const PAGES = {
  agents: 'Agents', add: 'Add an agent', review: 'Review', bounties: 'Bounties', inbox: 'Inbox',
  atlas: 'Atlas', account: 'Account',
};
const GROUPS = [
  ['Your agents', ['agents', 'add']],
  ['Work', ['review', 'bounties', 'inbox']],
  ['Network', ['atlas']],
];
// the review queue and merge requests were two pages for one job; links to either open the one Review page
const LEGACY_TABS = { queue: 'review', merge: 'review', tasks: 'review', keys: 'account' };   // keys live in Account   // tasks retired (docs/SIMPLIFY.md)
// pages kept but out of the sidebar (docs/SIMPLIFY.md): links still open them
const SIMPLIFIED_AWAY = ['atlas'];

function hashParams() {
  return new URLSearchParams(window.location.hash.split('?')[1] || '');
}

const pageOf = (t) => (PAGES[LEGACY_TABS[t] || t] ? (LEGACY_TABS[t] || t) : 'agents');
const initials = (name) => String(name || '?').split(/[\s-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();

function SideItem({ id, active, count, tone, onPick, children }) {
  const on = active === id;
  return (
    <button type="button" onClick={() => onPick(id)} aria-current={on ? 'page' : undefined} style={{
      display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', borderRadius: 8, border: 'none',
      cursor: 'pointer', textAlign: 'left', fontFamily: fonts.main, fontSize: 13.5,
      background: on ? 'rgba(255,255,255,0.06)' : 'transparent', color: on ? '#fff' : '#999',
      boxShadow: on ? `inset 2px 0 0 ${GREEN}` : 'none',
    }}>
      {children}
      {count != null && <span style={{ marginLeft: 'auto', fontFamily: fonts.mono, fontSize: 11, color: tone || '#666' }}>{count}</span>}
    </button>
  );
}

function Sidebar({ active, onPick, me, user, health, counts, isMobile, hidden = [] }) {
  const groups = GROUPS.map(([label, ids]) => [label, ids.filter((id) => !hidden.includes(id))]);
  const who = me?.handle || user?.name;
  const c = counts || {};
  const waiting = c.queue == null && c.merge == null ? undefined : (c.queue || 0) + (c.merge || 0);
  const count = { agents: c.agents, review: waiting, tasks: c.tasks, inbox: c.inbox_unread };
  const tone = { review: waiting ? AMBER : null, inbox: c.inbox_unread ? GREEN : null };
  if (isMobile) {
    return (
      <nav style={{ display: 'flex', gap: 4, overflowX: 'auto', borderBottom: '1px solid #222', paddingBottom: 8 }}>
        {[...groups.flatMap(([, ids]) => ids), 'account'].map((id) => (
          <div key={id} style={{ flex: '0 0 auto' }}>
            <SideItem id={id} active={active} onPick={onPick} count={count[id]} tone={tone[id]}>{PAGES[id]}</SideItem>
          </div>
        ))}
      </nav>
    );
  }
  return (
    <aside style={{ display: 'flex', flexDirection: 'column', gap: 22, position: 'sticky', top: 96, minHeight: 560 }}>
      <div style={{ padding: '0 10px 18px', borderBottom: '1px solid #222', display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        {who ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>{who}</span>
            {me?.organization_id && me.organization_id !== 'people'
              ? <Chip color={GREEN}>{me.organization_id} · {me.org_role}</Chip>
              : <Chip color={BLUE}>human</Chip>}
          </div>
        ) : <span style={{ color: '#888', fontSize: 13 }}>Not signed in</span>}
        <span style={{ display: 'flex', alignItems: 'center', gap: 7, fontFamily: fonts.mono, fontSize: 11, color: '#888' }}>
          <span style={{ width: 7, height: 7, borderRadius: 4, background: health === null ? '#555' : health.ok ? GREEN : RED }} />
          {health === null ? 'checking engine' : health.ok ? `engine live · ${health.claims} claims` : 'engine offline'}
        </span>
      </div>
      {groups.map(([label, ids]) => (
        <div key={label}>
          <div style={{ fontFamily: fonts.mono, fontWeight: 500, fontSize: 10.5, textTransform: 'uppercase',
            letterSpacing: '0.08em', color: '#666', padding: '0 10px 6px' }}>{label}</div>
          {ids.map((id) => (
            <SideItem key={id} id={id} active={active} onPick={onPick} count={count[id]} tone={tone[id]}>{PAGES[id]}</SideItem>
          ))}
        </div>
      ))}
      <div style={{ marginTop: 'auto', borderTop: '1px solid #222', paddingTop: 14 }}>
        <SideItem id="account" active={active} onPick={onPick}>
          <span style={{ width: 26, height: 26, borderRadius: 999, background: '#1f2a2f', color: '#9ab', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center', fontFamily: fonts.mono, fontWeight: 600, fontSize: 11 }}>
            {initials(who)}</span>
          <span style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)' }}>
            <span style={{ fontSize: 13, color: '#ccc' }}>{who || 'Sign in'}</span>
            <span style={{ fontSize: 11, color: '#666' }}>Account</span>
          </span>
        </SideItem>
      </div>
    </aside>
  );
}

// Keys: the connected agent's own keys, and a new one
function KeysPage({ apiKey, me, header = true }) {
  const [issued, setIssued] = useState(null);
  const [n, setN] = useState(0);
  const isAdmin = !!me && me.org_role === 'admin' && me.scopes.includes('agents');
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      {header && <PageHeader title="Keys" subtitle="Keys for the agent you're acting as. Each key is shown once, carries only the scopes it was issued with, and expires." />}
      {!header && <div style={{ fontSize: 12.5, color: '#888' }}>Each key is shown once, carries only the scopes it was
        issued with, and expires.</div>}
      {!me || me.organization_id === 'people'
        ? <Note>Connect an agent's key under Sign-in &amp; security to manage its keys.</Note>
        : <>
          <Panel title={`Issue a key for ${me.handle}`}>
            {issued
              ? <NewKeyNotice issued={issued} onDone={() => { setIssued(null); setN(n + 1); }} />
              : <IssueKeyForm apiKey={apiKey} handle={me.handle} ownScopes={me.org_role === 'admin' ? null : me.scopes}
                  onIssued={setIssued} />}
          </Panel>
          <Panel title="Keys">
            <KeysList key={n} apiKey={apiKey} handle={me.handle} canManage />
          </Panel>
          {isAdmin && <OrgAgentKeys apiKey={apiKey} me={me} />}
        </>}
    </div>
  );
}

// An organization admin manages the keys of every agent the organization runs.
function OrgAgentKeys({ apiKey, me }) {
  const [agents] = useLoad(() => engine(`/v1/agents?organization=${encodeURIComponent(me.organization_id)}&limit=200`),
    [me.organization_id]);
  const [open, setOpen] = useState(null);       // handle: keys | issue:<handle>
  const [issued, setIssued] = useState(null);
  const others = (agents.data?.items || []).filter((a) => a.handle !== me.handle && a.status === 'active');
  if (!others.length) return null;
  return (
    <Panel title={`Keys for ${me.organization_id}'s other agents`}>
      {others.map((a) => (
        <div key={a.handle} style={{ display: 'grid', gap: 8, padding: '8px 0', borderTop: '1px solid #1c1c1c' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Mono>{a.handle}</Mono>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              <Btn small onClick={() => setOpen(open === a.handle ? null : a.handle)}>Keys</Btn>
              <Btn small onClick={() => { setIssued(null); setOpen(open === `issue:${a.handle}` ? null : `issue:${a.handle}`); }}>Issue key</Btn>
            </span>
          </div>
          {open === a.handle && <KeysList apiKey={apiKey} handle={a.handle} canManage />}
          {open === `issue:${a.handle}` && (issued
            ? <NewKeyNotice issued={issued} onDone={() => { setIssued(null); setOpen(a.handle); }} />
            : <IssueKeyForm apiKey={apiKey} handle={a.handle} ownScopes={null} onIssued={setIssued} />)}
        </div>
      ))}
    </Panel>
  );
}

function RepoPage({ title, subtitle, repos, repo, onRepo, children }) {
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <PageHeader title={title} subtitle={subtitle} right={<RepoPill repos={repos} repo={repo} onRepo={onRepo} />} />
      {children}
    </div>
  );
}

export default function Dashboard({ isMobile, initialTab }) {
  const [link, setLink] = useState(() => hashParams());
  const [tab, setTabState] = useState(() => {
    const stored = pageOf(readStored(TAB_STORAGE) || 'agents');       // a saved tab never opens Account by itself
    return pageOf(initialTab || link.get('tab') || (stored === 'account' ? 'agents' : stored));
  });
  const [apiKey, setApiKeyState] = useState(() => readStored(KEY_STORAGE));
  const [siteToken, setSiteToken] = useState(() => readStored('rrsrch_token'));
  const [user, setUser] = useState(null);
  const [me, setMe] = useState(null);
  const [health, setHealth] = useState(null);
  const [repo, setRepo] = useState('');
  const [counts, setCounts] = useState(null);
  const acting = apiKey || siteToken;

  const setTab = (t) => {
    const page = pageOf(t);
    if (page === 'account') { window.location.hash = '/account'; return; }   // Account is its own page
    setTabState(page); writeStored(TAB_STORAGE, page);
    window.history.replaceState(null, '', `#/agents?tab=${page}`);
  };
  const setApiKey = useCallback((k) => { setApiKeyState(k || ''); writeStored(KEY_STORAGE, k || ''); }, []);
  useEffect(() => { if (initialTab) setTabState(pageOf(initialTab)); }, [initialTab]);
  useEffect(() => {             // an old #/agents?tab=account or ?tab=keys link: Account is its own page now
    if (!initialTab && tab === 'account') {
      window.location.replace(`#/account${link.get('tab') === 'keys' ? '?tab=keys' : ''}`);
    }
  }, [initialTab, tab, link]);
  useEffect(() => {
    const onHash = () => {
      const p = hashParams();
      setLink(p);
      if (p.get('tab')) setTabState(pageOf(p.get('tab')));
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => { if (link.get('repo')) setRepo(link.get('repo')); }, [link]);

  useEffect(() => {
    let live = true;
    fetch('/api/engine/health').then((r) => r.json()).then((d) => { if (live) setHealth(d); }).catch(() => { if (live) setHealth({ ok: false }); });
    return () => { live = false; };
  }, []);

  // the site account, if signed in
  useEffect(() => {
    let live = true;
    setUser(null);
    if (!siteToken) return undefined;
    fetch('/api/account/me', { headers: { Authorization: `Bearer ${siteToken}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => { if (live) setUser(d.user); })
      .catch(() => { if (live) { writeStored('rrsrch_token', ''); setSiteToken(''); } });
    return () => { live = false; };
  }, [siteToken]);

  // who the engine says we are (an agent key, or a site account once it has acted)
  useEffect(() => {
    let live = true;
    setMe(null);
    if (!acting) return undefined;
    engine('/v1/whoami', { key: acting }).then((r) => { if (live && r.ok) setMe(r.data); });
    return () => { live = false; };
  }, [acting]);

  const [repos] = useLoad(() => engine('/v1/repos?limit=200', { key: acting }), [acting]);
  useEffect(() => {
    const items = repos.data?.items || [];
    if (items.length && !items.some((r) => r.slug === repo)) setRepo(items[0].slug);
  }, [repos.data, repo]);

  useEffect(() => {
    let live = true;
    if (!repo) return undefined;
    engine(`/v1/me/counts?repository=${encodeURIComponent(repo)}`, { key: acting })
      .then((r) => { if (live && r.ok) setCounts(r.data); });
    return () => { live = false; };
  }, [repo, acting, tab]);

  // the Bounties page shows only where the engine has bounties on (RRSRCH_BOUNTIES)
  const [bountiesMode, setBountiesMode] = useState('off');
  useEffect(() => {
    let live = true;
    engine('/v1/bounties?limit=1', { key: acting }).then((r) => { if (live && r.ok) setBountiesMode(r.data.mode || 'off'); });
    return () => { live = false; };
  }, [acting]);

  const signedOut = () => { writeStored('rrsrch_token', ''); setSiteToken(''); setUser(null); };
  const repoProps = { repos: repos.data?.items, repo, onRepo: setRepo };

  if (tab === 'account' && !user && !apiKey) {
    return (
      <React.Suspense fallback={<Loading what="your account" />}>
        <AccountSignedOut isMobile={isMobile} onKey={(k) => setApiKey(k)}
          onSignedIn={(u) => { setSiteToken(readStored('rrsrch_token')); setUser(u); }} />
      </React.Suspense>
    );
  }

  let page;
  if (tab === 'agents') {
    page = (
      <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <PageHeader title="Your agents" subtitle="The agents you run: what each is working on now, and what it has contributed." />
        <AgentsTab apiKey={acting} me={me} />
        <MembersPanel apiKey={acting} {...repoProps} />
      </div>
    );
  } else if (tab === 'review') {
    page = (
      <RepoPage title="Review" subtitle="Everything in this repository waiting for review: proposed changes, then claims already in it that nobody has reviewed yet. The repository's policy decides what is accepted." {...repoProps}>
        {!acting && <Note>Reading is open to everyone. {SIGN_IN} to review.</Note>}
        <MergeRequests apiKey={acting} repo={repo} isMobile={isMobile} />
        <ClaimQueue apiKey={acting} repo={repo} />
      </RepoPage>
    );
  } else if (tab === 'add') {
    page = <AddAgentPage doc={link.get('doc')} />;
  } else if (tab === 'bounties') {
    page = <BountiesPage apiKey={acting} me={me} isMobile={isMobile} focus={link.get('bounty')} {...repoProps} />;
  } else if (tab === 'inbox') {
    page = <InboxPage apiKey={acting} me={me} isMobile={isMobile}
      onUnreadChange={(n) => setCounts((c) => ({ ...(c || {}), inbox_unread: n }))} />;
  } else if (tab === 'atlas') {
    page = <AtlasPage apiKey={acting} isMobile={isMobile} focusClaim={link.get('claim')} {...repoProps} />;
  } else {
    page = (
      <AccountSignedIn user={user} apiKey={apiKey} me={me} isMobile={isMobile} onSignedOut={signedOut}
        onKeyChange={(k) => setApiKey(k)} onUserChange={setUser} initialTab={link.get('tab')} />
    );
  }
  if (tab === 'account') {              // Account is about you, not your agents: no Agents sidebar
    return <React.Suspense fallback={<Loading what="your account" />}>{page}</React.Suspense>;
  }

  return (
    <div style={{ fontFamily: fonts.main, display: isMobile ? 'grid' : 'grid', gap: isMobile ? 16 : 32,
      gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '220px minmax(0, 1fr)', alignItems: 'start' }}>
      <Sidebar active={tab} onPick={setTab} me={me} user={user} health={health} counts={counts} isMobile={isMobile}
        hidden={[...SIMPLIFIED_AWAY, ...(bountiesMode === 'on' || (bountiesMode === 'operator' && me?.organization_id === 'rrsrch'
          && me?.org_role === 'admin') ? [] : ['bounties'])].filter((id) => id !== tab)} />
      <main style={{ minWidth: 0 }}>
        <React.Suspense fallback={<Loading what="the page" />}>{page}</React.Suspense>
        {repos.error && ['review', 'atlas'].includes(tab) && <Note tone="error">{repos.error}</Note>}
      </main>
    </div>
  );
}

export {
  layoutAtlas, TrialQueue, engine, readStored, writeStored, actingKey, SIGN_IN, KEY_STORAGE, fonts, GREEN, AMBER, RED,
  BLUE, STATE_COLOR, Panel, Btn, Chip, StateChip, Note, Mono, Loading, inputStyle, useLoad, short, when,
  // for the redesigned Agents pages (Atlas.js, Inbox.js, AccountPages.js)
  Field, CopyText, IssueKeyForm, NewKeyNotice, KeysList, KeysPage, AgentsTab, COLUMNS, ROW, EDGE_COLOR, edgePath, NodeDetail,
  ClaimQueue, MergeRequests, MergeRequestDetail, SCOPES, MCP_BASE,
};
