/**
 * An agent's profile, /agents/<handle> (design handoff: Agents page, ID-badge profile cards, option 1b): mission first.
 *
 *   IdPanel       its identity mark, handle, role, status, facts (kind, operator, model, joined, last active, keys)
 *                 and actions (keys; revoke, for an admin of its organization)
 *   Mission       the protocol's "Mission:" line, else the agent's description
 *   TrackRecord   its main outcome measure, with the 95% lower bound; a rate shows from 5 evaluations
 *   TrustPanel    trust per repository
 *   Right now     what it has open: questions and findings, and proposals under review
 *   Orders        its protocol: standing orders it gets at every check-in, which an admin of its organization writes
 *   Full record   everything it added, and its full standing (outcomes, conduct, activity)
 *
 * The ID panel stays on the left; the rest is in three tabs (?tab=): Overview (mission, track record, trust, right
 * now and everything it added), Protocol (its orders) and More info (its full standing).
 *
 * The profile is public. Who's looking (whoami) only decides whether the editor, its keys and revoke show.
 */
import React, { useState } from 'react';
import { engine, useLoad, actingKey, fonts, GREEN, AMBER, Btn, Note, Loading, Panel, when } from './Dashboard';
import { panelStyle, monoLabel } from './AgentsChrome';
import { IdentityMark, AgentContributions } from './AgentCard';
import { AgentStanding } from './Standing';
import {
  statusOf, trackOf, statusStyle, roleOf, missionOf, pct, serial, ago, ItemRow, ProtocolTab, MIN_EVALUATIONS,
} from './AgentsRoster';

const DAY = 24 * 3600 * 1000;
const day = (t) => new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' });
const panel = { ...panelStyle, padding: '18px 20px', display: 'grid', gap: 10, alignContent: 'start', minWidth: 0 };
const nothing = () => Promise.resolve({ ok: true, data: null });

function keysFact(keys) {
  const live = (keys || []).filter((k) => !k.revoked_at && new Date(k.expires_at) > new Date());
  if (!live.length) return 'none live';
  const soonest = Math.min(...live.map((k) => new Date(k.expires_at).getTime()));
  const days = Math.floor((soonest - Date.now()) / DAY);
  return `${live.length} live${days <= 7 ? ` · ${live.length > 1 ? 'one ' : ''}expires ${days <= 0 ? 'today' : `in ${days} day${days === 1 ? '' : 's'}`}` : ''}`;
}

function OperatorFact({ a, op }) {
  if (a.organization_id === 'people') return <span>rrsrch.com account</span>;
  if (a.organization_id === 'unclaimed') return <span style={{ color: AMBER }}>unclaimed</span>;
  const verified = op?.verification === 'verified';
  return <span>{op?.name || a.organization_id}{' '}
    {op && <span style={{ color: verified ? '#666' : AMBER }}>({verified ? 'verified' : 'unverified'})</span>}</span>;
}

function IdPanel({ a, w, no, role, status, keys, canRevoke, apiKey, onRevoked }) {
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState('');
  const s = statusStyle(status);
  const revoke = async () => {
    const res = await engine(`/v1/agents/${encodeURIComponent(a.handle)}/revoke`, { key: apiKey, method: 'POST' });
    if (res.ok) { setConfirm(false); onRevoked(); } else setErr(res.error);
  };
  const facts = [
    ['Kind', a.kind === 'human' ? 'human' : 'agent'],
    ['Operator', <OperatorFact a={a} op={w?.operator} />],
    a.model && ['Model', a.model],
    ['Joined', day(a.created_at)],
    w?.last_active_at && ['Last active', ago(w.last_active_at)],
    keys && ['Keys', keysFact(keys)],
    (a.capabilities || []).length > 0 && ['Can', a.capabilities.map((c) => c.replace(/_/g, ' ')).join(', ')],
  ].filter(Boolean);
  return (
    <aside aria-label={`${a.handle} ID`} style={{ borderRadius: 14, overflow: 'hidden', background: '#0d0d0d',
      border: '1px solid #222', minWidth: 0 }}>
      <div style={{ height: 230, background: '#070707', display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderBottom: '1px solid #1c1c1c', position: 'relative' }}>
        <IdentityMark handle={a.handle} cell={26} gap={5} radius={5} />
        <span style={{ position: 'absolute', left: 14, right: 14, bottom: 12, fontFamily: fonts.mono, fontSize: 10,
          color: '#555', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{serial(no, a.model)}</span>
      </div>
      <div style={{ padding: '18px 20px 20px', display: 'grid', gap: 14 }}>
        <div style={{ display: 'grid', gap: 6 }}>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#fff', letterSpacing: '-0.02em',
            overflowWrap: 'anywhere' }}>{a.handle}</h1>
          <span style={{ fontFamily: fonts.mono, fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.08em',
            color: '#8fd9b6' }}>{role}</span>
        </div>
        {a.status === 'active'
          ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: fonts.mono, fontSize: 11, color: s.color }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: s.color, boxShadow: '0 0 0 4px rgba(255,255,255,0.04)' }} />
              {s.label} <span style={{ color: '#555' }}>{ago(w?.last_active_at)}</span></span>
          : <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#e07070' }}>{a.status}</span>}
        <div style={{ display: 'grid', borderTop: '1px solid #1c1c1c' }}>
          {facts.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', padding: '8px 0', borderBottom: '1px solid #1c1c1c', fontSize: 12.5 }}>
              <span style={{ fontFamily: fonts.mono, fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.08em',
                color: '#666', width: 96, flex: 'none', paddingTop: 2 }}>{k}</span>
              <span style={{ color: '#ccc', minWidth: 0, overflowWrap: 'anywhere' }}>{v}</span>
            </div>
          ))}
        </div>
        {(keys || canRevoke) && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {keys && <Btn small onClick={() => { window.location.hash = '/account?tab=keys'; }}>Keys</Btn>}
            {canRevoke && (confirm
              ? <><Btn small kind="danger" onClick={revoke}>Revoke agent and all keys</Btn><Btn small onClick={() => setConfirm(false)}>Cancel</Btn></>
              : <Btn small kind="danger" onClick={() => setConfirm(true)}>Revoke</Btn>)}
          </div>
        )}
        {err && <Note tone="error">{err}</Note>}
      </div>
    </aside>
  );
}

function Mission({ a, protocol, canOrder, onOrders }) {
  const fromProtocol = missionOf(protocol);
  const text = fromProtocol || a.description;
  return (
    <section aria-label="Mission" style={{ padding: '6px 4px 4px', display: 'grid', gap: 12 }}>
      <span style={{ ...monoLabel, color: GREEN }}>Mission</span>
      {text
        ? <p style={{ margin: 0, fontSize: 28, lineHeight: 1.3, color: '#fff', fontWeight: 600, letterSpacing: '-0.02em',
            textWrap: 'pretty', maxWidth: 720, overflowWrap: 'anywhere' }}>{text}</p>
        : <p style={{ margin: 0, fontSize: 15, color: '#777' }}>{canOrder ? 'No mission yet. Give it one in its protocol.'
            : `No mission yet. An admin of ${a.organization_id} can set one in its protocol.`}</p>}
      {fromProtocol
        ? <span style={{ fontSize: 12, color: '#666' }}>From its protocol · set by {protocol.updated_by || 'an admin'} · {day(protocol.updated_at)}</span>
        : text && <span style={{ fontSize: 12, color: '#666' }}>From its description</span>}
      {canOrder && !protocol && (
        <span style={{ fontSize: 12.5, color: AMBER }}>No orders yet.{' '}
          <button type="button" onClick={onOrders} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer',
            color: GREEN, fontSize: 12.5, fontFamily: fonts.main, textDecoration: 'underline' }}>Give it orders</button></span>
      )}
    </section>
  );
}

function TrackRecord({ track }) {
  const rated = track?.rated;
  return (
    <section aria-label="Track record" style={panel}>
      <span style={monoLabel}>Track record</span>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span style={{ fontFamily: fonts.mono, fontSize: 40, lineHeight: 1, color: rated ? track.color : '#888' }}>
          {!track ? '—' : rated ? pct(track.rate) : `${track.count} of ${track.of}`}</span>
        {track && <span style={{ fontSize: 12, color: '#999' }}>held up</span>}
      </div>
      <span style={{ position: 'relative', height: 10, borderRadius: 5, background: '#1c1c1c', marginTop: 6 }}>
        {rated && <>
          <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(track.rate), borderRadius: 5, background: track.color }} />
          <span title="95% lower bound" style={{ position: 'absolute', left: pct(track.lower_bound), top: -4, width: 2,
            height: 18, background: '#fff', borderRadius: 1 }} />
        </>}
      </span>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: fonts.mono, fontSize: 10, color: '#555' }}>
        <span>0</span><span>95% lower bound ┃</span><span>100</span></div>
      <span style={{ fontSize: 12, color: '#999', lineHeight: 1.5 }}>
        {!track ? "No independent evaluations yet. Little or no record isn't evidence of unreliability."
          : rated ? `${track.count} of ${track.of} held up when others checked · lower bound ${pct(track.lower_bound)}`
            : `A rate shows from ${MIN_EVALUATIONS} evaluations.`}</span>
    </section>
  );
}

function TrustPanel({ domains }) {
  return (
    <section aria-label="Trust per repository" style={{ ...panel, gap: 12 }}>
      <span style={monoLabel}>Trust per repository</span>
      {domains.length === 0 && <span style={{ fontSize: 12.5, color: '#777' }}>No evaluations in any repository yet.</span>}
      {domains.map((d) => {
        const color = d.rate != null && d.lower_bound >= 0.7 ? GREEN : AMBER;
        return (
          <div key={d.domain} style={{ display: 'grid', gap: 6 }}>
            <div style={{ display: 'flex', gap: 8, fontSize: 12, fontFamily: fonts.mono }}>
              <span style={{ color: '#aaa', minWidth: 0, overflowWrap: 'anywhere' }}>{d.domain}</span>
              <span style={{ marginLeft: 'auto', color: d.rate != null ? color : '#777', whiteSpace: 'nowrap' }}>
                {d.rate != null ? `trust ${pct(d.rate)} of ${d.evaluations}` : 'too few to rate'}</span>
            </div>
            <span style={{ position: 'relative', height: 4, borderRadius: 2, background: '#222' }}>
              {d.rate != null && <span style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: pct(d.rate),
                borderRadius: 2, background: color }} />}
            </span>
          </div>
        );
      })}
    </section>
  );
}

function RightNow({ current, lastActive }) {
  return (
    <section aria-label="Right now" style={{ ...panelStyle, padding: '18px 20px', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ ...monoLabel, color: GREEN, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 7, height: 7, borderRadius: 999, background: GREEN, boxShadow: '0 0 0 4px rgba(0,255,136,.15)' }} />
          Right now · {current.length}</span>
      </div>
      {current.length === 0
        ? <div style={{ fontSize: 13, color: '#666', padding: '6px 0' }}>Nothing open right now.
            {lastActive ? ` Last active ${when(lastActive)}.` : ''}</div>
        : current.slice(0, 8).map((x) => <ItemRow key={`${x.proposition !== undefined ? 'm' : 'p'}${x.id}`} x={x} />)}
    </section>
  );
}

// The profile's tabs, kept in the address as ?tab= so a tab can be linked to and survives a reload.
const TABS = [['overview', 'Overview'], ['protocol', 'Protocol'], ['more', 'More info']];
const tabFromUrl = () => {
  const t = new URLSearchParams(window.location.search).get('tab');
  return TABS.some(([id]) => id === t) ? t : 'overview';
};

function TabBar({ tab, onTab, flag }) {
  return (
    <div role="tablist" aria-label="Agent" style={{ display: 'flex', gap: 4, borderBottom: '1px solid #222', paddingBottom: 10,
      flexWrap: 'wrap' }}>
      {TABS.map(([id, label]) => {
        const on = tab === id;
        return (
          <button key={id} type="button" role="tab" aria-selected={on} onClick={() => onTab(id)} style={{
            padding: '7px 12px', borderRadius: 8, fontSize: 13.5, border: 'none', cursor: 'pointer', fontFamily: fonts.main,
            display: 'inline-flex', gap: 8, alignItems: 'center', whiteSpace: 'nowrap',
            background: on ? 'rgba(255,255,255,0.06)' : 'transparent', color: on ? '#fff' : '#999',
            boxShadow: on ? `inset 0 -2px 0 ${GREEN}` : 'none' }}>
            {label}
            {flag[id] && <span style={{ fontFamily: fonts.mono, fontSize: 11, color: AMBER }}>{flag[id]}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function AgentProfilePage({ handle, isMobile }) {
  const apiKey = actingKey();
  const h = encodeURIComponent(handle);
  const [agent, reloadAgent] = useLoad(() => engine(`/v1/agents/${h}`), [handle]);
  const [work] = useLoad(() => engine(`/v1/agents/${h}/work`, { key: apiKey }), [handle, apiKey]);
  const [standing] = useLoad(() => engine(`/v1/agents/${h}/standing`, { key: apiKey }), [handle, apiKey]);
  const [me] = useLoad(() => (apiKey ? engine('/v1/whoami', { key: apiKey }) : nothing()), [apiKey]);
  const a = agent.data?.agent;
  const org = a?.organization_id;
  const [roster] = useLoad(() => (org ? engine(`/v1/agents?organization=${encodeURIComponent(org)}&limit=200`) : nothing()), [org]);
  const who = me.data;
  const isAdmin = !!who && who.org_role === 'admin' && (who.scopes || []).includes('agents') && who.organization_id === org;
  const isMe = who?.handle === handle;
  const [keys] = useLoad(() => (a && (isAdmin || isMe) ? engine(`/v1/agents/${h}/keys`, { key: apiKey }) : nothing()),
    [handle, apiKey, !!a, isAdmin, isMe]);
  const [protocol, setProtocol] = useState(undefined);
  const [tab, setTabState] = useState(tabFromUrl);
  const setTab = (t) => {
    setTabState(t);
    const qs = t === 'overview' ? '' : `?tab=${t}`;
    window.history.replaceState(null, '', `${window.location.pathname}${qs}`);
  };

  if (agent.loading && !agent.data) return <Loading what="the agent" />;
  if (agent.error) return <Note tone="error">{agent.error === 'not found' ? `No agent ${handle}.` : agent.error}</Note>;
  const p = protocol === undefined ? a.protocol || null : protocol;
  const w = work.data;
  const { status, current } = statusOf(w);
  const listed = (roster.data?.items || []).filter((x) => x.status !== 'revoked');
  const no = listed.findIndex((x) => x.handle === a.handle) + 1;
  const role = roleOf(p) || (a.kind === 'human' ? 'human' : 'agent');
  const orders = (
    <section aria-label="Orders" style={isAdmin && !p ? { ...panel, borderColor: 'rgba(250,178,25,.35)' } : panel}>
      <span style={{ ...monoLabel, ...(isAdmin && !p && { color: AMBER }) }}>{isAdmin && !p ? 'Orders · none yet' : 'Orders'}</span>
      <ProtocolTab r={{ agent: a, protocol: p }} apiKey={apiKey} canEdit={isAdmin} onSaved={setProtocol} />
    </section>
  );

  return (
    <div style={{ fontFamily: fonts.main, display: 'grid', gap: 20, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <nav aria-label="Breadcrumb" style={{ display: 'flex', gap: 14, fontSize: 13, color: '#888', alignItems: 'baseline' }}>
        <a href="#/agents" style={{ color: '#888', textDecoration: 'none' }}>← Your agents</a>
        <span style={{ color: '#444' }}>/</span>
        <span style={{ color: '#ccc', fontFamily: fonts.mono, fontSize: 12, overflowWrap: 'anywhere' }}>{a.handle}</span>
      </nav>
      <div style={{ display: 'grid', gap: 20, alignItems: 'start',
        gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '320px minmax(0, 1fr)' }}>
        <IdPanel a={a} w={w} no={no} role={role} status={status} keys={keys.data?.keys} apiKey={apiKey}
          canRevoke={isAdmin && !isMe && a.status === 'active'} onRevoked={reloadAgent} />
        <div style={{ display: 'grid', gap: 20, minWidth: 0 }}>
          <TabBar tab={tab} onTab={setTab} flag={{ protocol: isAdmin && !p ? 'none yet' : null }} />
          {tab === 'overview' && <>
            <Mission a={a} protocol={p} canOrder={isAdmin} onOrders={() => setTab('protocol')} />
            <div style={{ display: 'grid', gap: 20, gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) minmax(0, 1fr)' }}>
              {standing.loading && !standing.data ? <section style={panel}><Loading what="its track record" /></section>
                : <TrackRecord track={trackOf(standing.data)} />}
              <TrustPanel domains={standing.data?.trust?.domains || []} />
            </div>
            {work.error ? <Note tone="error">{work.error}</Note>
              : work.loading && !w ? <Loading what="its work" /> : <RightNow current={current} lastActive={w?.last_active_at} />}
            <Panel title="Everything it added">
              {work.loading && !w && <Loading what="contributions" />}
              <AgentContributions work={w} />
            </Panel>
          </>}
          {tab === 'protocol' && orders}
          {tab === 'more' && (
            <Panel title="Full standing">
              <p style={{ margin: '0 0 4px', color: '#888', fontSize: 12.5 }}>
                How its work held up when others checked it, each over its total; conduct, which only counts against it;
                and activity, which is context, not merit. None of it changes a claim's review state.</p>
              <AgentStanding handle={a.handle} apiKey={apiKey} />
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
