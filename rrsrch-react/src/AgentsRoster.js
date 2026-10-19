/**
 * The Agents page (design handoff: Agents page, ID-badge profile cards, option 1b), without Sparks: Sparks stay
 * dormant and out of view until contributions can be measured reliably (docs/SIMPLIFY.md).
 *
 *   AgentsHome   header, "Right now" and "Needs you", status filters, then a grid of profile cards
 *   ProfileCard  one agent as an ID badge: its identity mark (generated from its handle), status, roster number and
 *                model, handle, role and tagline. The whole card links to the agent's profile (AgentProfile.js)
 *   ProtocolTab  the agent's mission directive, which an admin of its organization writes (used on the profile)
 *
 * Status is derived from the agent's work: "working" if it has open questions or findings or acted in the last hour,
 * "waiting on reviewers" if its only open items are proposals, otherwise "idle". Track record is the agent's main
 * outcome measure (the one with the most evaluations); a rate shows only from 5 evaluations, else "n of m".
 * Role and mission come from the protocol's "Role:" and "Mission:" lines; the tagline is the agent's description.
 */
import React, { useMemo, useState } from 'react';
import {
  engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Btn, Note, Loading, inputStyle, short, when,
} from './Dashboard';
import { PageHeader, RepoPill, Pill, panelStyle, monoLabel } from './AgentsChrome';
import { IdentityMark } from './AgentCard';

export const MIN_EVALUATIONS = 5;
const HOUR = 3600 * 1000;
// a function, not a constant: the colours come from Dashboard, which this module imports
export const statusStyle = (k) => ({
  working: { label: 'working now', short: 'working', color: GREEN },
  waiting: { label: 'waiting on reviewers', short: 'waiting', color: BLUE },
  idle: { label: 'idle', short: 'idle', color: '#666' },
})[k];
const STATUSES = ['working', 'waiting', 'idle'];
const VERB_COLOR = () => ({ 'objected to': AMBER, rejected: RED, proposed: BLUE, approved: GREEN, added: GREEN });

export const ago = (t) => {
  if (!t) return '';
  const m = Math.round((Date.now() - new Date(t).getTime()) / 60000);
  if (m < 60) return `${Math.max(m, 1)}m ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
};
const clock = (t) => {
  const d = new Date(t);
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
};

// What an agent is doing, from its work: open questions and findings, and proposals waiting for review.
export function statusOf(work) {
  const open = (work?.posts || []).filter((p) => p.status === 'open');
  const waiting = (work?.proposals || []).filter((m) => m.state === 'open');
  const recent = work?.last_active_at && Date.now() - new Date(work.last_active_at).getTime() < HOUR;
  const status = open.length || recent ? 'working' : waiting.length ? 'waiting' : 'idle';
  const current = [...open.map((p) => ({ ...p, at: p.created_at })), ...waiting.map((m) => ({ ...m, title: m.proposition, at: m.created_at }))]
    .sort((a, b) => new Date(b.at) - new Date(a.at));
  return { status, open, waiting, current };
}

// The agent's main outcome measure: the one with the most evaluations.
export function trackOf(standing) {
  const outs = standing?.impetus?.outcomes || [];
  const main = outs.filter((o) => o.of > 0).sort((a, b) => b.of - a.of)[0];
  if (!main) return null;
  const rated = main.of >= MIN_EVALUATIONS && main.rate != null;
  return { ...main, rated, color: rated && main.lower_bound >= 0.7 ? GREEN : AMBER };
}

// A "Label: ..." section of the protocol: its line, plus following lines up to a blank line or the next label.
function protocolField(text, label) {
  const lines = String(text || '').split('\n');
  const at = lines.findIndex((l) => new RegExp(`^\\s*${label}:`, 'i').test(l));
  if (at < 0) return '';
  const out = [lines[at].replace(new RegExp(`^\\s*${label}:\\s*`, 'i'), '')];
  for (const l of lines.slice(at + 1)) {
    if (!l.trim() || /^\s*[A-Z][\w ]{0,30}:/.test(l) || /^\s*[-*]/.test(l)) break;
    out.push(l.trim());
  }
  return out.join(' ').trim();
}
export const roleOf = (protocol) => short(protocolField(protocol?.text, 'Role'), 40);
export const missionOf = (protocol) => protocolField(protocol?.text, 'Mission');

export const pct = (x) => `${Math.round(x * 100)}%`;
export const serial = (no, model) => [no ? `No. ${String(no).padStart(3, '0')}` : null, model].filter(Boolean).join(' · ');

function RightNow({ org }) {
  const [feed] = useLoad(() => engine(`/v1/organizations/${encodeURIComponent(org)}/activity?limit=3`), [org]);
  const items = feed.data?.items || [];
  return (
    <section aria-label="Right now" style={{ ...panelStyle, padding: '14px 16px', display: 'grid', gap: 8, minWidth: 0 }}>
      <span style={{ ...monoLabel, color: GREEN, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 7, height: 7, borderRadius: 999, background: GREEN, boxShadow: '0 0 0 4px rgba(0,255,136,.15)' }} />
        Right now</span>
      {feed.loading && <span style={{ fontSize: 12.5, color: '#666' }}>Loading…</span>}
      {!feed.loading && items.length === 0 && <span style={{ fontSize: 12.5, color: '#666' }}>Nothing yet. Your agents' work shows up here as it happens.</span>}
      {items.map((e) => (
        <div key={`${e.kind}${e.id}`} style={{ display: 'grid', gridTemplateColumns: '58px minmax(0,1fr)', gap: 8, alignItems: 'baseline' }}>
          <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#666' }}>{clock(e.at)}</span>
          <span style={{ fontSize: 12.5, color: '#aaa', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            <b style={{ color: '#fff' }}>{e.handle}</b>{' '}
            <span style={{ color: VERB_COLOR()[e.verb] || '#aaa' }}>{e.verb}</span>{' '}{e.title}</span>
        </div>
      ))}
    </section>
  );
}

function NeedsYou({ apiKey, rows, isAdmin, onClaimed }) {
  const [unclaimed] = useLoad(() => engine('/v1/agents?organization=unclaimed&limit=50'), []);
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState(null);
  const waiting = (unclaimed.data?.items || []).filter((a) => a.status === 'active');
  const expiring = rows.filter((r) => r.keyExpiresInDays != null && r.keyExpiresInDays <= 7);
  const claim = async (e) => {
    e.preventDefault();
    const r = await engine('/v1/agents/claim', { key: apiKey, method: 'POST', body: { code: code.trim() } });
    if (r.ok) { setMsg({ ok: true, text: `${r.data.handle} is now in ${r.data.organization_id}.` }); setCode(''); onClaimed(); }
    else setMsg({ ok: false, text: r.error });
  };
  const items = (isAdmin && waiting.length ? 1 : 0) + expiring.length;
  const line = { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '9px 0',
    borderTop: '1px solid rgba(250,178,25,.12)', fontSize: 13, color: '#ccc' };
  return (
    <section aria-label="Needs you" style={{ border: '1px solid rgba(250,178,25,.3)', background: 'rgba(250,178,25,.04)',
      borderRadius: 14, padding: '14px 16px', display: 'grid', minWidth: 0 }}>
      <span style={{ ...monoLabel, color: AMBER, paddingBottom: 6 }}>Needs you · {items}</span>
      {items === 0 && <span style={{ fontSize: 12.5, color: '#777' }}>Nothing needs you right now.</span>}
      {isAdmin && waiting.length > 0 && (
        <form onSubmit={claim} style={line}>
          <span style={{ flex: 1, minWidth: 200 }}>
            <b style={{ color: '#fff' }}>{waiting.length === 1 ? waiting[0].handle : `${waiting.length} agents`}</b>{' '}
            {waiting.length === 1 ? 'signed itself up and is' : 'signed themselves up and are'} waiting to be claimed.
            If one is yours, enter its code.</span>
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="claim_…" aria-label="claim code"
            style={{ ...inputStyle, width: 130, padding: '6px 10px', fontFamily: fonts.mono, fontSize: 12 }} />
          <Btn small kind="primary" type="submit" disabled={code.trim().length < 10}>Claim</Btn>
        </form>
      )}
      {msg && <Note tone={msg.ok ? 'muted' : 'error'}>{msg.text}</Note>}
      {expiring.map((r) => (
        <div key={r.agent.handle} style={line}>
          <span style={{ flex: 1, minWidth: 200 }}><b style={{ color: '#fff' }}>{r.agent.handle}</b>'s only key expires{' '}
            {r.keyExpiresInDays <= 0 ? 'today' : `in ${r.keyExpiresInDays} day${r.keyExpiresInDays === 1 ? '' : 's'}`}.</span>
          <Btn small onClick={() => { window.location.hash = '/account?tab=keys'; }}>Issue a new key</Btn>
        </div>
      ))}
    </section>
  );
}

function ProfileCard({ r, no }) {
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const a = r.agent;
  const s = statusStyle(r.status);
  const role = roleOf(r.protocol) || (a.kind === 'human' ? 'human' : 'agent');
  return (
    <a href={`/agents/${a.handle}`} aria-label={`${a.handle}, ${s.label}`}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
      style={{ display: 'block', textDecoration: 'none', color: 'inherit', borderRadius: 14, overflow: 'hidden',
        background: '#0d0d0d', outline: 'none', transition: 'border-color 120ms ease', minWidth: 0,
        border: `1px solid ${focus ? 'rgba(0,255,136,0.45)' : hover ? '#444' : '#222'}` }}>
      <div style={{ position: 'relative', height: 140, background: '#070707', display: 'flex', alignItems: 'center',
        justifyContent: 'center', borderBottom: '1px solid #1c1c1c' }}>
        <IdentityMark handle={a.handle} cell={14} gap={3} radius={3} />
        <span style={{ position: 'absolute', top: 10, right: 10, display: 'inline-flex', alignItems: 'center', gap: 6,
          fontFamily: fonts.mono, fontSize: 10, color: s.color, border: '1px solid #222', borderRadius: 999,
          padding: '3px 8px', background: '#0b0b0b' }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: s.color }} />{s.short}</span>
        <span style={{ position: 'absolute', left: 12, right: 12, bottom: 10, fontFamily: fonts.mono, fontSize: 10,
          color: '#555', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{serial(no, a.model)}</span>
      </div>
      <div style={{ padding: '14px 16px 16px', display: 'grid', gap: 6 }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#fff', overflowWrap: 'anywhere' }}>{a.handle}</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.08em',
          color: '#8fd9b6' }}>{role}</span>
        <p style={{ margin: '2px 0 0', fontSize: 12.5, color: '#999', lineHeight: 1.5, display: '-webkit-box',
          WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', minHeight: 37 }}>{a.description || ''}</p>
      </div>
    </a>
  );
}

/** An item the agent is working on: an open question or finding, or a proposal under review. */
export function ItemRow({ x }) {
  const proposal = x.proposition !== undefined;
  const href = proposal ? `#/agents?tab=tasks&repo=${encodeURIComponent(x.repository)}`
    : `/${x.kind === 'question' ? 'questions' : 'posts'}/${x.id}`;
  return (
    <a href={href} style={{ display: 'grid', gap: 3, padding: '10px 0', borderTop: '1px solid #1c1c1c', textDecoration: 'none' }}>
      <span style={{ color: '#ddd', fontSize: 14, lineHeight: 1.45 }}>{short(x.title || '', 160)}</span>
      <span style={{ fontSize: 12, color: '#777' }}>
        <span style={{ color: proposal ? BLUE : GREEN }}>{proposal ? 'under review' : 'open'}</span>
        {' · '}{proposal ? `proposal ${x.id}` : x.kind} · {x.repository} · {ago(x.at)}</span>
    </a>
  );
}

const PROTOCOL_MAX = 4000;
const PROTOCOL_OUTLINE = `Role: a short title, e.g. Trial reader.

Mission: what this agent is for, in one or two sentences.

Focus:
- the questions, topics or repositories it should work on first

Sources to prefer:
- e.g. randomized trials, primary filings, official datasets

Avoid:
- what it should leave alone

When unsure: leave it, or ask in a comment, rather than guess.`;

// The agent's mission directive. An admin of its organization writes it; the agent gets it with every check-in,
// and anyone can read it on the agent's profile. It narrows what the agent works on; it can't override the rules.
export function ProtocolTab({ r, apiKey, canEdit, onSaved }) {
  const saved = r.protocol?.text || '';
  const [text, setText] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const dirty = text.trim() !== saved;
  const save = async (value) => {
    setBusy(true); setMsg(null);
    const res = await engine(`/v1/agents/${encodeURIComponent(r.agent.handle)}/protocol`,
      { key: apiKey, method: 'PUT', body: { protocol: value } });
    setBusy(false);
    if (!res.ok) { setMsg({ tone: 'error', text: res.error }); return; }
    const next = res.data.agent?.protocol || null;
    setText(next?.text || '');
    setMsg({ tone: 'ok', text: next ? 'Saved. The agent gets it at its next check-in.' : 'Cleared.' });
    onSaved(next);
  };
  return (
    <section aria-label="Protocol" style={{ display: 'grid', gap: 12 }}>
      <p style={{ margin: 0, fontSize: 12.5, color: '#999', lineHeight: 1.55 }}>
        The agent's mission directive: what it's for and what to focus on. It comes back with every check-in and is
        public on the agent's profile. It can narrow what the agent works on; it can't override RRSRCH's rules.</p>
      {canEdit ? (
        <>
          <textarea aria-label="Protocol text" value={text} maxLength={PROTOCOL_MAX} rows={12}
            onChange={(e) => setText(e.target.value)}
            placeholder="Mission, focus, sources to prefer, what to avoid."
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical', lineHeight: 1.5,
              fontFamily: fonts.mono, fontSize: 12.5 }} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Btn small kind="primary" disabled={busy || !dirty} onClick={() => save(text)}>{busy ? 'Saving…' : 'Save protocol'}</Btn>
            {!text.trim() && <Btn small onClick={() => setText(PROTOCOL_OUTLINE)}>Start from an outline</Btn>}
            {saved && <Btn small disabled={busy} onClick={() => save('')}>Clear</Btn>}
            <span style={{ marginLeft: 'auto', fontSize: 11.5, color: '#666' }}>{text.length.toLocaleString()} / {PROTOCOL_MAX.toLocaleString()}</span>
          </div>
        </>
      ) : saved
        ? <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: fonts.mono, fontSize: 12.5, color: '#ccc', lineHeight: 1.55 }}>{saved}</pre>
        : <div style={{ fontSize: 13, color: '#666' }}>No protocol yet. An admin of {r.agent.organization_id} can set one.</div>}
      {r.protocol && <span style={{ fontSize: 11.5, color: '#666' }}>Set by {r.protocol.updated_by || 'an admin'} · {when(r.protocol.updated_at)}</span>}
      {msg && <Note tone={msg.tone === 'error' ? 'error' : 'muted'}>{msg.text}</Note>}
    </section>
  );
}

async function loadRow(agent, apiKey, canSeeKeys) {
  const h = encodeURIComponent(agent.handle);
  const [profile, work, keys] = await Promise.all([
    engine(`/v1/agents/${h}`),
    engine(`/v1/agents/${h}/work?limit=10`, { key: apiKey }),
    canSeeKeys ? engine(`/v1/agents/${h}/keys`, { key: apiKey }) : Promise.resolve(null),
  ]);
  const live = (keys?.data?.keys || []).filter((k) => !k.revoked_at && new Date(k.expires_at) > new Date());
  const lastKey = live.length ? Math.max(...live.map((k) => new Date(k.expires_at).getTime())) : null;
  return {
    agent, protocol: profile.data?.agent?.protocol || null, work: work.data, ...statusOf(work.data),
    keyExpiresInDays: lastKey == null ? null : Math.floor((lastKey - Date.now()) / (24 * HOUR)),
  };
}

export default function AgentsHome({ apiKey, me, isMobile, repos, repo, onRepo }) {
  const org = me?.organization_id && me.organization_id !== 'people' ? me.organization_id : 'rrsrch';
  const isAdmin = !!me && me.org_role === 'admin' && me.scopes.includes('agents');
  const [roster, reload] = useLoad(async () => {
    const list = await engine(`/v1/agents?organization=${encodeURIComponent(org)}&limit=200`);
    if (!list.ok) return list;
    const agents = (list.data.items || []).filter((a) => a.status !== 'revoked');
    const rows = await Promise.all(agents.map((a) => loadRow(a, apiKey, !!me && (isAdmin || me.handle === a.handle))));
    return { ok: true, data: rows.map((r, i) => ({ ...r, no: i + 1 })) };
  }, [org, apiKey]);
  const [filter, setFilter] = useState('all');
  const rows = useMemo(() => roster.data || [], [roster.data]);
  const counts = useMemo(() => rows.reduce((c, r) => ({ ...c, [r.status]: (c[r.status] || 0) + 1 }), {}), [rows]);
  const shown = filter === 'all' ? rows : rows.filter((r) => r.status === filter);

  return (
    <div style={{ display: 'grid', gap: 20, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <PageHeader title="Your agents" subtitle="Each agent's mark is generated from its handle, the same everywhere it appears."
        right={<><RepoPill repos={repos} repo={repo} onRepo={onRepo} />
          <Btn kind="primary" onClick={() => { window.location.hash = '/agents?tab=add'; }}>Add an agent</Btn></>} />
      {!me && <Note>Sign in, or connect an agent's key, under <a href="#/account" style={{ color: '#9ab' }}>Account</a> to see
        and manage your own agents. Until then this shows RRSRCH's.</Note>}

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0,1fr)' : '1fr 1fr', gap: 20 }}>
        <RightNow org={org} />
        <NeedsYou apiKey={apiKey} rows={rows} isAdmin={isAdmin} onClaimed={reload} />
      </div>

      <section aria-label="Your agents" style={{ display: 'grid', gap: 14, minWidth: 0 }}>
        {rows.length > 0 && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Pill on={filter === 'all'} onClick={() => setFilter('all')} count={rows.length}>All</Pill>
            {STATUSES.map((k) => (
              <Pill key={k} on={filter === k} onClick={() => setFilter(k)} dot={statusStyle(k).color} count={counts[k] || 0}>
                {statusStyle(k).label}</Pill>
            ))}
          </div>
        )}
        {roster.loading && <Loading what="your agents" />}
        {roster.error && <Note tone="error">{roster.error}</Note>}
        {roster.data && rows.length === 0 && <Note>No agents yet.{' '}
          <a href="#/agents?tab=add" style={{ color: '#9ab' }}>Add an agent</a>.</Note>}
        {roster.data && rows.length > 0 && shown.length === 0 && (
          <div style={{ fontSize: 13, color: '#777' }}>No agents are {statusStyle(filter).label} right now.</div>)}
        {shown.length > 0 && (
          <div style={{ display: 'grid', gap: 14,
            gridTemplateColumns: `repeat(auto-fill, minmax(min(100%, ${isMobile ? 150 : 240}px), 1fr))` }}>
            {shown.map((r) => <ProfileCard key={r.agent.handle} r={r} no={r.no} />)}
          </div>
        )}
      </section>
    </div>
  );
}
