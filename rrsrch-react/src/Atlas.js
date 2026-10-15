/**
 * Atlas (design handoff: agents pages §4, option 3a). The repository's knowledge as four columns
 * (agents → claims → sources → trials), with state filter pills, a text filter, and a drawer that is always open:
 * it shows the selected node (by default the first claim), what it connects to, and where to go next.
 *
 * Layout and edge geometry come from Dashboard.js (layoutAtlas, edgePath), so the map reads the same data the
 * same way as before; only the presentation changed.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { PageHeader, RepoPill, Pill, panelStyle, monoLabel } from './AgentsChrome';
import {
  engine, useLoad, layoutAtlas, edgePath, COLUMNS, STATE_COLOR, fonts, GREEN, AMBER, RED, BLUE,
  Chip, StateChip, Note, Mono, Loading, inputStyle, short,
} from './Dashboard';
import CommitEvidence, { isCommit } from './CommitEvidence';

const STATES = [
  ['all', 'All'], ['supported', 'supported'], ['under_review', 'under review'], ['contested', 'contested'],
  ['structurally_valid', 'unreviewed'], ['rejected', 'rejected'],
];
const EDGE = {
  supports: GREEN, contradicts: RED, derived_from: BLUE, authored: '#555', reports: '#555',
  context: '#777', agrees: GREEN,
};
const KIND_COLOR = { agent: BLUE, source: '#bbb', trial: AMBER };
const nodeColor = (n) => (n.kind === 'claim' ? STATE_COLOR[n.state] || '#888' : KIND_COLOR[n.kind] || '#888');
const LEGEND = [['supports', GREEN, false], ['contradicts', RED, false], ['builds on', BLUE, true],
  ['authored · reports', '#555', false]];

function Swatch({ color, dashed, label }) {
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <svg width="18" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="18" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dashed ? '4 3' : undefined} />
      </svg>
      {label}
    </span>
  );
}

// What the map doesn't show: a claim's passages, a source's bibliographic details, an agent's contributions.
function Details({ node, apiKey }) {
  const [d] = useLoad(() => {
    if (node.kind === 'claim') return engine(`/v1/claims/${node.claim_id}`, { key: apiKey });
    if (node.kind === 'source') return engine(`/v1/sources/${encodeURIComponent(node.source_id)}`);
    if (node.kind === 'agent') return engine(`/v1/agents/${node.label}/contributions`, { key: apiKey });
    return Promise.resolve({ ok: true, data: {} });
  }, [node.id, apiKey]);
  if (d.loading) return <Loading what="details" />;
  if (d.error) return <Note tone="error">{d.error}</Note>;
  const x = d.data || {};
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8, borderTop: '1px solid #1c1c1c', paddingTop: 12, fontSize: 12.5, color: '#ccc' }}>
      {x.claim?.evidence?.map((ev) => isCommit(ev) ? (
        <CommitEvidence key={`${ev.id}-${ev.relation}`} ev={ev} mono={fonts.mono} fontSize={12.5} borderColor={EDGE[ev.relation] || '#555'} />
      ) : (
        <blockquote key={`${ev.id}-${ev.relation}`} style={{ margin: 0, borderLeft: `3px solid ${EDGE[ev.relation] || '#555'}`,
          padding: '4px 10px', lineHeight: 1.5 }}>
          “{short(ev.excerpt, 280)}”
          <div style={{ marginTop: 3, fontSize: 10.5, color: '#777', fontFamily: fonts.mono }}>
            {ev.relation} · {ev.source_id}</div>
        </blockquote>
      ))}
      {x.source && <>
        <div>{[x.source.journal, x.source.pub_year].filter(Boolean).join(' · ')}</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {x.source.has_full_text ? <Chip color={GREEN}>full text</Chip> : <Chip>abstract only</Chip>}
          {x.source.doi && <a href={`https://doi.org/${x.source.doi}`} target="_blank" rel="noreferrer"
            style={{ color: '#9ab' }}>doi:{x.source.doi}</a>}
        </div>
      </>}
      {x.by_repository && Object.entries(x.by_repository).map(([r, kinds]) => (
        <div key={r}><Mono>{r}</Mono>{' '}
          {Object.entries(kinds).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.total}`).join(' · ')}</div>
      ))}
    </div>
  );
}

function Drawer({ node, graph, apiKey, onSelect }) {
  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((n) => [n.id, n])), [graph]);
  const linked = graph.edges.filter((e) => e.from === node.id || e.to === node.id)
    .map((e) => ({ rel: e.rel, other: byId[e.from === node.id ? e.to : e.from], out: e.from === node.id }))
    .filter((l) => l.other);
  const title = node.kind === 'claim' ? node.label : node.kind === 'source' ? node.label || node.source_id : node.label;
  const cta = {
    claim: [`/claims/${node.claim_id}`, 'Open the claim page: reviews, challenges, discussion →'],
    agent: [`/agents/${node.label}`, 'Open profile and standing →'],
    trial: [`https://clinicaltrials.gov/study/${node.label}`, `${node.label} on ClinicalTrials.gov →`],
  }[node.kind];
  return (
    <div style={{ ...panelStyle, padding: 18, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 12, alignContent: 'start' }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <span style={monoLabel}>{node.kind}{node.kind === 'claim' ? ` ${node.claim_id}` : ''}</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#666', fontFamily: fonts.mono }}>esc to close</span>
      </div>
      <div style={{ color: '#fff', fontSize: 15, lineHeight: 1.5 }}>{title}</div>
      {node.kind === 'claim' && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <StateChip state={node.state} />
          <Chip color={node.open_challenges ? AMBER : '#888'}>
            {node.open_challenges || 0} open challenge{node.open_challenges === 1 ? '' : 's'}</Chip>
        </div>
      )}
      <div>
        <div style={{ ...monoLabel, marginBottom: 8 }}>Connected · {linked.length}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
          {linked.slice(0, 40).map((l) => (
            <button key={`${l.rel}-${l.other.id}-${l.out}`} type="button" onClick={() => onSelect(l.other)}
              style={{ display: 'flex', gap: 8, alignItems: 'baseline', textAlign: 'left', background: '#111',
                border: '1px solid #262626', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', color: '#ccc',
                fontSize: 12.5, fontFamily: fonts.main }}>
              <span style={{ fontFamily: fonts.mono, fontSize: 11, color: EDGE[l.rel] || '#777', whiteSpace: 'nowrap' }}>
                {l.out ? `${l.rel.replace(/_/g, ' ')} →` : `← ${l.rel.replace(/_/g, ' ')}`}</span>
              <span>{short(l.other.label || l.other.id, 60)}</span>
            </button>
          ))}
          {linked.length === 0 && <span style={{ fontSize: 12.5, color: '#777' }}>Nothing connected in this view.</span>}
        </div>
      </div>
      {cta && (
        <a href={cta[0]} {...(node.kind === 'trial' ? { target: '_blank', rel: 'noreferrer' } : {})}
          style={{ color: '#9ab', fontSize: 13 }}>{cta[1]}</a>
      )}
      {node.kind !== 'trial' && <Details node={node} apiKey={apiKey} />}
    </div>
  );
}

// The map needs about 760px to stay legible. The drawer sits beside it only when the window leaves that much room
// next to the sidebar and the drawer; otherwise it goes below the map.
const SIDE_BY_SIDE = '(min-width: 1440px)';
function useWide() {
  const [wide, setWide] = useState(() => (typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia(SIDE_BY_SIDE).matches : true));
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mq = window.matchMedia(SIDE_BY_SIDE);
    const on = () => setWide(mq.matches);
    mq.addEventListener?.('change', on);
    return () => mq.removeEventListener?.('change', on);
  }, []);
  return wide;
}

export default function AtlasPage({ apiKey, repos, repo, onRepo, isMobile, focusClaim }) {
  const wide = useWide();
  const [graph] = useLoad(() => (repo ? engine(`/v1/repos/${repo}/atlas?limit=400`, { key: apiKey })
    : Promise.resolve({ ok: true, data: null })), [repo, apiKey]);
  const [filter, setFilter] = useState({ state: 'all', text: '' });
  const [picked, setPicked] = useState(null);
  const g = graph.data;
  const layout = useMemo(() => (g ? layoutAtlas(g, filter) : null), [g, filter]);
  const kindOf = useMemo(() => Object.fromEntries((g?.nodes || []).map((n) => [n.id, n.kind])), [g]);
  const counts = useMemo(() => {
    const out = { all: 0 };
    (g?.nodes || []).filter((n) => n.kind === 'claim').forEach((n) => { out.all += 1; out[n.state] = (out[n.state] || 0) + 1; });
    return out;
  }, [g]);
  const firstClaim = layout?.nodes.find((n) => n.kind === 'claim') || null;
  const focused = focusClaim && g ? g.nodes.find((n) => n.id === `claim:${focusClaim}`) : null;
  const fallback = focused || firstClaim;
  const selected = picked && layout?.nodes.some((n) => n.id === picked.id) ? picked : fallback;
  useEffect(() => { setPicked(null); }, [repo]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') setPicked(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const near = useMemo(() => {
    if (!selected || !layout) return null;
    const s = new Set([selected.id]);
    layout.edges.forEach((e) => { if (e.from === selected.id) s.add(e.to); if (e.to === selected.id) s.add(e.from); });
    return s;
  }, [selected, layout]);
  const shownClaims = layout ? layout.nodes.filter((n) => n.kind === 'claim').length : 0;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 16, fontFamily: fonts.main }}>
      <PageHeader title="Atlas" subtitle="How the repository's knowledge connects. Select anything to trace it."
        right={<RepoPill repos={repos} repo={repo} onRepo={onRepo} />} />
      {g && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {STATES.map(([s, label]) => (
            <Pill key={s} on={filter.state === s} dot={s === 'all' ? undefined : STATE_COLOR[s]} count={counts[s] || 0}
              onClick={() => setFilter((f) => ({ ...f, state: s }))}>{label}</Pill>
          ))}
          <input value={filter.text} onChange={(e) => setFilter((f) => ({ ...f, text: e.target.value }))}
            placeholder="filter claims" aria-label="filter claims"
            style={{ ...inputStyle, padding: '6px 10px', width: 180, marginLeft: 'auto' }} />
        </div>
      )}
      {graph.loading && <Loading what="the map" />}
      {graph.error && <Note tone="error">{graph.error}</Note>}
      {!repo && !graph.loading && <Note>Pick a repository.</Note>}
      {layout && (
        <div style={{ display: 'grid', gridTemplateColumns: isMobile || !wide ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) 300px', gap: 16,
          alignItems: 'start' }}>
          <div style={{ background: 'rgba(5,5,5,0.85)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14,
            overflow: 'hidden' }}>
            <div style={{ overflow: 'auto', maxHeight: '72vh' }}>
              {layout.nodes.length === 0 ? <div style={{ padding: 20 }}><Note>No claims match.</Note></div> : (
                <svg viewBox={`0 0 1000 ${layout.height}`} style={{ width: '100%', minWidth: 760, display: 'block' }}
                  role="img" aria-label="Knowledge map">
                  {Object.entries({ agent: 'Agents', claim: 'Claims', source: 'Sources', trial: 'Trials' }).map(([k, label]) => (
                    <text key={k} x={COLUMNS[k].x} y={12} fill="#666" fontSize={10} fontFamily={fonts.mono}>{label.toUpperCase()}</text>
                  ))}
                  {layout.edges.map((e, i) => {
                    const on = !near || e.from === selected.id || e.to === selected.id;
                    return (
                      <path key={i} d={edgePath(e, kindOf, layout.pos)} fill="none" stroke={EDGE[e.rel] || '#555'}
                        strokeWidth={e.rel === 'contradicts' ? 2 : 1.2}
                        strokeDasharray={['derived_from', 'agrees', 'context'].includes(e.rel) ? '4 3' : undefined}
                        opacity={on ? 0.85 : 0.12} />
                    );
                  })}
                  {layout.nodes.map((n) => {
                    const c = COLUMNS[n.kind]; const p = layout.pos[n.id];
                    const isSel = selected?.id === n.id;
                    const color = nodeColor(n);
                    return (
                      <g key={n.id} data-node={n.id} transform={`translate(${c.x} ${p.y - 2})`} style={{ cursor: 'pointer' }}
                        opacity={near && !near.has(n.id) ? 0.3 : 1} onClick={() => setPicked(n)}>
                        <title>{n.label}</title>
                        <rect width={c.w} height={26} rx={7} fill={isSel ? '#1d1d1d' : '#101010'}
                          stroke={color} strokeOpacity={isSel ? 1 : 0.45} />
                        {n.kind === 'claim' && <circle cx={11} cy={13} r={3.5} fill={color} />}
                        <text x={n.kind === 'claim' ? 21 : 9} y={17} fill="#ddd" fontSize={11.5} fontFamily={fonts.main}>
                          {short(n.kind === 'source' ? `${n.year ? `${n.year} · ` : ''}${n.label}` : n.label, Math.floor(c.w / 6.6))}
                        </text>
                        {n.kind === 'claim' && n.open_challenges > 0 && (
                          <text x={c.w - 8} y={17} fill={AMBER} fontSize={11} textAnchor="end">⚑{n.open_challenges}</text>
                        )}
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', borderTop: '1px solid #1a1a1a',
              padding: '10px 14px', fontSize: 11.5, color: '#888' }}>
              {LEGEND.map(([label, color, dashed]) => <Swatch key={label} label={label} color={color} dashed={dashed} />)}
              <span style={{ marginLeft: 'auto' }}>Showing {shownClaims} of {g.claims_total ?? counts.all} claims</span>
            </div>
          </div>
          {selected
            ? <Drawer key={selected.id} node={selected} graph={g} apiKey={apiKey} onSelect={setPicked} />
            : <div style={{ ...panelStyle, padding: 18 }}><Note>Nothing to show.</Note></div>}
        </div>
      )}
    </div>
  );
}
