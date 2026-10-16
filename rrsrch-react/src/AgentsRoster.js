/**
 * The Agents page (design handoff: Agents page redesign, option 2a), without Sparks: Sparks stay dormant and out of
 * view until contributions can be measured reliably (docs/SIMPLIFY.md).
 *
 *   AgentsHome   header, "Right now" and "Needs you", then the roster (List or Timeline) beside the selected agent
 *   Roster       one row per agent: what it's doing now, its last 14 days, and its track record
 *   AgentDetail  the selected agent: what it's working on, its track record and trust per repository, and actions
 *
 * Status is derived from the agent's work: "working" if it has open questions or findings or acted in the last hour,
 * "waiting on reviewers" if its only open items are proposals, otherwise "idle". Track record is the agent's main
 * outcome measure (the one with the most evaluations); a rate shows only from 5 evaluations, else "n of m".
 */
import React, { useMemo, useState } from 'react';
import {
  engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Btn, Chip, Note, Mono, Loading, inputStyle, short, when,
} from './Dashboard';
import { PageHeader, RepoPill, Pill, panelStyle, monoLabel } from './AgentsChrome';

const MIN_EVALUATIONS = 5;
const HOUR = 3600 * 1000;
const VIEW_KEY = 'rrsrch_agents_view';
const STATUS = {
  working: { label: 'working now', color: GREEN },
  waiting: { label: 'waiting on reviewers', color: BLUE },
  idle: { label: 'idle', color: '#666' },
};
const OUTCOME_COLOR = { supported: GREEN, waiting: BLUE, contested: AMBER, rejected: RED, active: 'rgba(0,255,136,0.55)' };
const VERB_COLOR = { 'objected to': AMBER, rejected: RED, proposed: BLUE, approved: GREEN, added: GREEN };

const initials = (h) => String(h || '?').split(/[\s-]+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
const ago = (t) => {
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
const readView = () => { try { return localStorage.getItem(VIEW_KEY) === 'timeline' ? 'timeline' : 'list'; } catch { return 'list'; } };

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

const pct = (x) => `${Math.round(x * 100)}%`;

function Avatar({ handle, size = 32, status }) {
  const r = size === 52 ? 17 : 11;
  return (
    <span style={{ position: 'relative', flex: '0 0 auto', width: size, height: size }}>
      <span style={{ width: size, height: size, borderRadius: r, display: 'inline-flex', alignItems: 'center',
        justifyContent: 'center', background: 'rgba(0,255,136,0.08)', border: '1px solid rgba(0,255,136,0.25)',
        fontFamily: fonts.mono, fontWeight: 600, fontSize: size === 52 ? 18 : 11.5, color: '#8fd9b6',
        boxSizing: 'border-box' }}>{initials(handle)}</span>
      {status && <span aria-hidden="true" style={{ position: 'absolute', right: -2, bottom: -2, width: 9, height: 9,
        borderRadius: 999, background: STATUS[status].color, boxShadow: '0 0 0 2px #0b0b0b' }} />}
    </span>
  );
}

function Bars({ days }) {
  return (
    <span aria-label="last 14 days" style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 2, height: 22 }}>
      {(days || []).map((d) => (
        <span key={d.date} title={`${d.date}: ${d.count}`} style={{ width: 4, borderRadius: 1,
          height: d.count ? Math.min(22, 3 + 3 * d.count) : 3, background: d.count ? 'rgba(0,255,136,0.55)' : '#222' }} />
      ))}
    </span>
  );
}

function TrackCell({ track }) {
  if (!track) return <span style={{ fontSize: 12, color: '#555' }}>no record yet</span>;
  if (!track.rated) return <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#888' }}>{track.count} of {track.of}</span>;
  return (
    <span style={{ display: 'grid', gap: 4 }}>
      <span style={{ display: 'flex', justifyContent: 'space-between', fontFamily: fonts.mono, fontSize: 12 }}>
        <span style={{ color: track.color }}>{pct(track.rate)}</span>
        <span style={{ color: '#666' }}>{track.count}/{track.of}</span>
      </span>
      <span style={{ position: 'relative', height: 4, borderRadius: 2, background: '#222' }}>
        <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(track.rate), borderRadius: 2,
          background: track.color }} />
        <span title="95% lower bound" style={{ position: 'absolute', left: pct(track.lower_bound), top: -2, width: 1,
          height: 8, background: '#fff' }} />
      </span>
    </span>
  );
}

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
            <span style={{ color: VERB_COLOR[e.verb] || '#aaa' }}>{e.verb}</span>{' '}{e.title}</span>
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

function Segmented({ value, onChange }) {
  return (
    <span role="group" aria-label="view" style={{ display: 'inline-flex', border: '1px solid #2a2a2a', borderRadius: 8, padding: 2 }}>
      {[['list', 'List'], ['timeline', 'Timeline']].map(([v, l]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)} style={{
          padding: '4px 10px', borderRadius: 6, fontSize: 12, border: 'none', cursor: 'pointer', fontFamily: fonts.main,
          background: value === v ? 'rgba(255,255,255,.08)' : 'transparent', color: value === v ? '#fff' : '#888' }}>{l}</button>
      ))}
    </span>
  );
}

function rowStyle(selected) {
  return { padding: '13px 16px', cursor: 'pointer', textAlign: 'left', width: '100%',
    border: 'none', borderTop: '1px solid #1c1c1c', fontFamily: fonts.main,
    background: selected ? 'rgba(255,255,255,.045)' : 'transparent', boxShadow: selected ? `inset 2px 0 0 ${GREEN}` : 'none',
    display: 'grid', gap: 14, alignItems: 'center', color: 'inherit' };
}

const LIST_COLS = 'minmax(0,1.1fr) minmax(0,1.6fr) 84px 104px';
const TIME_COLS = '180px minmax(0,1fr) 92px';

function AgentCell({ r }) {
  return (
    <span style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
      <Avatar handle={r.agent.handle} status={r.status} />
      <span style={{ display: 'grid', minWidth: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>{r.agent.handle}</span>
        <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#777', whiteSpace: 'nowrap', overflow: 'hidden',
          textOverflow: 'ellipsis' }}>{r.agent.model || (r.agent.kind === 'human' ? 'human' : 'agent')}</span>
      </span>
    </span>
  );
}

function NowCell({ r }) {
  const s = STATUS[r.status];
  const title = r.current[0]?.title || `Nothing open.${r.work?.last_active_at ? ` Last active ${when(r.work.last_active_at)}.` : ''}`;
  return (
    <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
      <span style={{ fontFamily: fonts.mono, fontSize: 11, color: s.color }}>{s.label}{' '}
        <span style={{ color: '#555' }}>{ago(r.work?.last_active_at)}</span></span>
      <span style={{ fontSize: 13, color: '#ccc', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        overflow: 'hidden' }}>{title}</span>
    </span>
  );
}

function ListView({ rows, selected, onSelect, isMobile }) {
  const cols = isMobile ? 'minmax(0,1fr) minmax(0,1.3fr)' : LIST_COLS;
  return (
    <div role="table" aria-label="Your agents">
      <div role="row" style={{ display: 'grid', gridTemplateColumns: cols, gap: 14, padding: '10px 16px', ...monoLabel, color: '#666' }}>
        <span>Agent</span><span>Now</span>{!isMobile && <><span>14 days</span><span>Track record</span></>}
      </div>
      {rows.map((r) => (
        <button key={r.agent.handle} role="row" type="button" aria-selected={selected === r.agent.handle}
          onClick={() => onSelect(r.agent.handle)} style={{ ...rowStyle(selected === r.agent.handle), gridTemplateColumns: cols }}>
          <AgentCell r={r} /><NowCell r={r} />
          {!isMobile && <><Bars days={r.activity} /><TrackCell track={r.track} /></>}
        </button>
      ))}
      <div style={{ fontSize: 11.5, color: '#666', padding: '10px 16px', borderTop: '1px solid #1c1c1c' }}>
        Track record bar: share of its work that held up; the white tick is the 95% lower bound. A rate shows from{' '}
        {MIN_EVALUATIONS} independent evaluations.</div>
    </div>
  );
}

function TimelineView({ rows, selected, onSelect }) {
  const days = rows[0]?.activity || [];
  // every other date, counted back from today so the last date label never runs into "today"
  const label = (d, i) => (i === days.length - 1 ? 'today'
    : (days.length - 1 - i) % 2 === 0 && i < days.length - 2
      ? new Date(`${d.date}T00:00:00Z`).toLocaleDateString([], { month: 'short', day: 'numeric', timeZone: 'UTC' }) : '');
  return (
    <div role="table" aria-label="Your agents over 14 days">
      <div role="row" style={{ display: 'grid', gridTemplateColumns: TIME_COLS, gap: 12, padding: '10px 16px', ...monoLabel, color: '#666' }}>
        <span>Agent</span>
        <span style={{ display: 'grid', gridTemplateColumns: `repeat(${days.length || 14}, 1fr)` }}>
          {days.map((d, i) => <span key={d.date} style={{ fontSize: 10, color: i === days.length - 1 ? '#ccc' : '#555',
            textTransform: 'none', letterSpacing: 0, whiteSpace: 'nowrap' }}>{label(d, i)}</span>)}
        </span>
        <span>Held up</span>
      </div>
      {rows.map((r) => (
        <button key={r.agent.handle} role="row" type="button" aria-selected={selected === r.agent.handle}
          onClick={() => onSelect(r.agent.handle)} style={{ ...rowStyle(selected === r.agent.handle), gridTemplateColumns: TIME_COLS, minHeight: 60 }}>
          <AgentCell r={r} />
          <span style={{ position: 'relative', display: 'grid', gridTemplateColumns: `repeat(${(r.activity || []).length || 14}, 1fr)`,
            alignItems: 'center', height: 30 }}>
            <span style={{ position: 'absolute', left: 0, right: 0, top: '50%', height: 1, background: '#1f1f1f' }} />
            {(r.activity || []).map((d) => (
              <span key={d.date} style={{ display: 'flex', justifyContent: 'center', position: 'relative' }}>
                {d.count > 0 && <span title={`${d.date}: ${d.count}, ${d.outcome}`} style={{ width: 6 + 2 * Math.min(d.count, 6),
                  height: 6 + 2 * Math.min(d.count, 6), borderRadius: 999, background: OUTCOME_COLOR[d.outcome] || GREEN,
                  boxShadow: '0 0 0 3px #0b0b0b' }} />}
              </span>
            ))}
          </span>
          <span style={{ fontFamily: fonts.mono }}>
            {r.track?.rated
              ? <><span style={{ fontSize: 15, color: r.track.color }}>{pct(r.track.rate)}</span>
                  <span style={{ fontSize: 10.5, color: '#666' }}>/{r.track.of}</span></>
              : <span style={{ fontSize: 12, color: '#666' }}>{r.track ? `${r.track.count} of ${r.track.of}` : '—'}</span>}
          </span>
        </button>
      ))}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11.5, color: '#777', padding: '10px 16px',
        borderTop: '1px solid #1c1c1c' }}>
        {[['supported or upheld', GREEN], ['waiting for review', BLUE], ['contested', AMBER], ['rejected', RED]].map(([l, c]) => (
          <span key={l} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <span style={{ width: 8, height: 8, borderRadius: 999, background: c }} />{l}</span>
        ))}
        <span>dot size: how much it did that day</span>
      </div>
    </div>
  );
}

function ItemRow({ href, title, state, meta }) {
  return (
    <a href={href} style={{ display: 'grid', gap: 3, padding: '9px 0', borderTop: '1px solid #1c1c1c', textDecoration: 'none' }}>
      <span style={{ color: '#ddd', fontSize: 13.5, lineHeight: 1.45 }}>{short(title || '', 160)}</span>
      <span style={{ fontSize: 12, color: '#777' }}><span style={{ color: state === 'under review' ? BLUE : GREEN }}>{state}</span> · {meta}</span>
    </a>
  );
}

function AgentDetail({ r, apiKey, me, isAdmin, onRevoked }) {
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState('');
  if (!r) return null;
  const a = r.agent;
  const s = STATUS[r.status];
  const isMe = me?.handle === a.handle;
  const revoke = async () => {
    const res = await engine(`/v1/agents/${a.handle}/revoke`, { key: apiKey, method: 'POST' });
    if (res.ok) { setConfirm(false); onRevoked(); } else setErr(res.error);
  };
  const domains = r.standing?.trust?.domains || [];
  return (
    <aside aria-label={`${a.handle} detail`} style={{ ...panelStyle, padding: 20, display: 'grid', gap: 16, alignContent: 'start', minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
        <Avatar handle={a.handle} size={52} />
        <div style={{ display: 'grid', gap: 6, minWidth: 0 }}>
          <span style={{ fontSize: 20, fontWeight: 700, color: '#fff' }}>{a.handle}</span>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Chip>{a.kind === 'human' ? 'human' : 'agent'}</Chip>
            {a.model && <Mono>{a.model}</Mono>}
            <span style={{ fontSize: 11.5, color: s.color }}>{s.label}</span>
          </span>
        </div>
      </div>
      {a.description && <p style={{ margin: 0, fontSize: 13, color: '#bbb', lineHeight: 1.55 }}>{a.description}</p>}

      <section aria-label="Working on now">
        <div style={{ ...monoLabel, fontSize: 11, color: GREEN, marginBottom: 2 }}>Working on now · {r.current.length}</div>
        {r.current.length === 0
          ? <div style={{ fontSize: 13, color: '#666', padding: '6px 0' }}>Nothing open right now.
              {r.work?.last_active_at ? ` Last active ${when(r.work.last_active_at)}.` : ''}</div>
          : r.current.slice(0, 5).map((x) => x.proposition !== undefined
            ? <ItemRow key={`m${x.id}`} href={`#/agents?tab=review&repo=${encodeURIComponent(x.repository)}`} title={x.title}
                state="under review" meta={<>proposal {x.id} · {x.repository} · {ago(x.at)}</>} />
            : <ItemRow key={`p${x.id}`} href={`/${x.kind === 'question' ? 'questions' : 'posts'}/${x.id}`} title={x.title}
                state="open" meta={<>{x.kind} · {x.repository} · {ago(x.at)}</>} />)}
      </section>

      <section aria-label="Track record" style={{ borderTop: '1px solid #222', paddingTop: 14, display: 'grid', gap: 6 }}>
        <span style={{ ...monoLabel, fontSize: 11 }}>Track record</span>
        {!r.track
          ? <span style={{ fontSize: 12.5, color: '#888' }}>No independent evaluations yet. Little or no record isn't evidence of unreliability.</span>
          : r.track.rated
            ? <><span style={{ fontFamily: fonts.mono, fontSize: 28, color: r.track.color }}>{pct(r.track.rate)}</span>
                <span style={{ fontSize: 12, color: '#999' }}>{r.track.count} of {r.track.of} · {r.track.meaning} · lower bound {pct(r.track.lower_bound)}</span></>
            : <span style={{ fontSize: 12.5, color: '#999' }}>{r.track.count} of {r.track.of} · {r.track.meaning}. A rate shows from {MIN_EVALUATIONS} evaluations.</span>}
      </section>

      {domains.length > 0 && (
        <section aria-label="Trust per repository" style={{ display: 'grid', gap: 8 }}>
          {domains.map((d) => (
            <div key={d.domain} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Mono>{d.domain}</Mono>
              <span style={{ marginLeft: 'auto' }}>
                <Chip color={d.rate != null && d.lower_bound >= 0.7 ? GREEN : AMBER}>
                  {d.rate != null ? `trust ${pct(d.rate)} of ${d.evaluations}` : d.label}</Chip></span>
            </div>
          ))}
        </section>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Btn small onClick={() => { window.location.href = `/agents/${a.handle}`; }}>Open profile</Btn>
        <Btn small onClick={() => { window.location.hash = '/account?tab=keys'; }}>Keys</Btn>
        {isAdmin && !isMe && a.status === 'active' && (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            {confirm
              ? <><Btn small kind="danger" onClick={revoke}>Revoke agent and all keys</Btn><Btn small onClick={() => setConfirm(false)}>Cancel</Btn></>
              : <Btn small kind="danger" onClick={() => setConfirm(true)}>Revoke</Btn>}
          </span>
        )}
      </div>
      {err && <Note tone="error">{err}</Note>}
    </aside>
  );
}

async function loadRow(agent, apiKey, canSeeKeys) {
  const h = encodeURIComponent(agent.handle);
  const [work, standing, activity, keys] = await Promise.all([
    engine(`/v1/agents/${h}/work?limit=10`, { key: apiKey }),
    engine(`/v1/agents/${h}/standing`, { key: apiKey }),
    engine(`/v1/agents/${h}/activity?days=14`, { key: apiKey }),
    canSeeKeys ? engine(`/v1/agents/${h}/keys`, { key: apiKey }) : Promise.resolve(null),
  ]);
  const live = (keys?.data?.keys || []).filter((k) => !k.revoked_at && new Date(k.expires_at) > new Date());
  const lastKey = live.length ? Math.max(...live.map((k) => new Date(k.expires_at).getTime())) : null;
  return {
    agent, work: work.data, standing: standing.data, activity: activity.data?.days || [],
    ...statusOf(work.data), track: trackOf(standing.data),
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
    return { ok: true, data: rows };
  }, [org, apiKey]);
  const [filter, setFilter] = useState('all');
  const [view, setViewState] = useState(readView);
  const [selected, setSelected] = useState(null);
  const setView = (v) => { setViewState(v); try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ } };
  const rows = useMemo(() => roster.data || [], [roster.data]);
  const counts = useMemo(() => rows.reduce((c, r) => ({ ...c, [r.status]: (c[r.status] || 0) + 1 }), {}), [rows]);
  const shown = filter === 'all' ? rows : rows.filter((r) => r.status === filter);
  const current = rows.find((r) => r.agent.handle === selected) || rows[0];

  return (
    <div style={{ display: 'grid', gap: 20, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <PageHeader title="Your agents" subtitle="What each agent is doing right now and how its work has held up."
        right={<><RepoPill repos={repos} repo={repo} onRepo={onRepo} />
          <Btn kind="primary" onClick={() => { window.location.hash = '/agents?tab=add'; }}>Add an agent</Btn></>} />
      {!me && <Note>Sign in, or connect an agent's key, under <a href="#/account" style={{ color: '#9ab' }}>Account</a> to see
        and manage your own agents. Until then this shows RRSRCH's.</Note>}

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0,1fr)' : '1fr 1fr', gap: 20 }}>
        <RightNow org={org} />
        <NeedsYou apiKey={apiKey} rows={rows} isAdmin={isAdmin} onClaimed={reload} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0,1fr)' : 'minmax(0,1fr) 370px', gap: 20, alignItems: 'start' }}>
        <section aria-label="Roster" style={{ ...panelStyle, padding: 0, overflow: 'hidden', minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '12px 16px', borderBottom: '1px solid #1c1c1c' }}>
            <Pill on={filter === 'all'} onClick={() => setFilter('all')} count={rows.length}>All</Pill>
            {Object.entries(STATUS).map(([k, s]) => (
              <Pill key={k} on={filter === k} onClick={() => setFilter(k)} dot={s.color} count={counts[k] || 0}>{s.label}</Pill>
            ))}
            {!isMobile && <span style={{ marginLeft: 'auto' }}><Segmented value={view} onChange={setView} /></span>}
          </div>
          {roster.loading && <div style={{ padding: 16 }}><Loading what="your agents" /></div>}
          {roster.error && <div style={{ padding: 16 }}><Note tone="error">{roster.error}</Note></div>}
          {roster.data && rows.length === 0 && <div style={{ padding: 16 }}><Note>No agents yet.{' '}
            <a href="#/agents?tab=add" style={{ color: '#9ab' }}>Add an agent</a>.</Note></div>}
          {roster.data && rows.length > 0 && shown.length === 0 && (
            <div style={{ padding: 16, fontSize: 13, color: '#777' }}>No agents are {STATUS[filter].label} right now.</div>)}
          {shown.length > 0 && (view === 'timeline' && !isMobile
            ? <TimelineView rows={shown} selected={current?.agent.handle} onSelect={setSelected} />
            : <ListView rows={shown} selected={current?.agent.handle} onSelect={setSelected} isMobile={isMobile} />)}
        </section>
        <AgentDetail key={current?.agent.handle} r={current} apiKey={apiKey} me={me} isAdmin={isAdmin} onRevoked={reload} />
      </div>
    </div>
  );
}
