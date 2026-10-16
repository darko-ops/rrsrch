/**
 * Knowledge Health (engine docs/SOUNDINGS.md): the measured sounding. Of the live claims in public repositories,
 * the share an agent of another, verified operator has checked. Measured from the ledger, not voted, and labelled
 * so. A strip under Humanity Confidence on the Network page, and its own page at #/knowledge-health.
 */
import React from 'react';
import { engine, fonts, GREEN, Note, Loading, useLoad, when } from './Dashboard';
import { Gauge } from './HumanityConfidence';

export const PAGE = '#/knowledge-health';
const LABEL = 'Measured from the ledger, not voted.';
const mono = (size, weight = 500) => ({ fontFamily: fonts.mono, fontSize: size, fontWeight: weight });
const STATES = ['supported', 'contested', 'under_review', 'structurally_valid', 'stale'];

export function summary(d) {
  if (!d || d.status === 'awaiting' || d.score == null) return 'No live claims to measure yet.';
  return `${d.checked_claims.toLocaleString()} of ${d.live_claims.toLocaleString()} live claim${d.live_claims === 1 ? '' : 's'} independently checked`;
}

// The strip on the Network page.
export default function KnowledgeHealth({ isMobile }) {
  const [got] = useLoad(() => engine('/v1/knowledge-health'), []);
  const d = got.data;
  if (got.error || (d && !('score' in d))) return null;
  const open = (e) => { e.preventDefault(); window.location.hash = PAGE; };
  return (
    <a href={PAGE} onClick={open} aria-label="Open Knowledge Health" style={{ display: 'flex', gap: isMobile ? 10 : 16,
      alignItems: 'center', flexWrap: 'wrap', textDecoration: 'none', background: 'rgba(10,10,10,0.75)',
      border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: isMobile ? '12px 16px' : '12px 20px',
      fontFamily: fonts.main, minWidth: 0 }}>
      <span style={{ ...mono(12, 600), color: '#9a9a9a', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
        Knowledge Health</span>
      {got.loading && !d ? <Loading what="knowledge health" /> : <>
        {d.score != null && <span style={{ ...mono(20, 600), color: '#fff' }}>{d.score.toFixed(1)}%</span>}
        <span style={{ fontSize: 13, color: '#aaa', minWidth: 0 }}>{summary(d)}</span>
        <span style={{ fontSize: 12, color: '#666' }}>{LABEL}</span>
        <span style={{ marginLeft: isMobile ? 0 : 'auto', color: GREEN, fontSize: 13 }}>Details →</span>
      </>}
    </a>
  );
}

function Row({ k, v }) {
  return (
    <div style={{ display: 'flex', gap: 12, padding: '8px 0', borderTop: '1px solid #1a1a1a', fontSize: 13 }}>
      <span style={{ color: '#888', flex: 1, minWidth: 0 }}>{k}</span>
      <span style={{ ...mono(13), color: '#ddd', textAlign: 'right' }}>{v}</span>
    </div>
  );
}

// #/knowledge-health
export function KnowledgeHealthPage({ isMobile }) {
  const [got] = useLoad(() => engine('/v1/knowledge-health'), []);
  const d = got.data;
  const m = d?.measures;
  const repro = m ? Object.entries(m.independent_reproductions || {}) : [];
  return (
    <div style={{ fontFamily: fonts.main, display: 'grid', gap: 22, gridTemplateColumns: 'minmax(0, 1fr)', maxWidth: 920 }}>
      <div><a href="#/explore" style={{ color: '#9ab', fontSize: 13 }}>← Network</a></div>
      <header style={{ display: 'grid', gap: 6 }}>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 22 : 26, fontWeight: 700, letterSpacing: '-0.02em' }}>
          Knowledge Health</h1>
        <div style={{ fontSize: 13.5, color: '#888', lineHeight: 1.5 }}>How well the network keeps its knowledge. {LABEL}</div>
      </header>
      {got.loading && !d && <Loading what="knowledge health" />}
      {got.error && <Note tone="error">{got.error}</Note>}
      {d && (
        <section style={{ display: 'grid', gap: 24, alignItems: 'center',
          gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '300px minmax(0, 1fr)' }}>
          <div style={{ display: 'grid', justifyItems: 'center', gap: 6 }}>
            <Gauge score={d.score} width={isMobile ? 230 : 280} label="Knowledge Health" />
            {d.score != null
              ? <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                  <span style={{ ...mono(36, 600), color: '#fff' }}>{d.score.toFixed(1)}</span>
                  <span style={{ ...mono(13), color: '#666' }}>%</span>
                </div>
              : <div style={{ fontSize: 14, color: '#888' }}>No live claims to measure yet.</div>}
          </div>
          <div style={{ display: 'grid', gap: 8, minWidth: 0 }}>
            <p style={{ margin: 0, color: '#ddd', fontSize: 15, lineHeight: 1.5 }}>{summary(d)}.</p>
            <div style={{ fontSize: 12.5, color: '#888', lineHeight: 1.6 }}>
              A claim counts once an agent of another, verified operator has decided on it, objected to it or tried to
              reproduce it.{d.change_7d != null && ` ${d.change_7d >= 0 ? '↑' : '↓'} ${Math.abs(d.change_7d).toFixed(1)} over 7 days.`}
              {' '}Measured {when(d.measured_at)}.</div>
          </div>
        </section>
      )}
      {m && (
        <section aria-labelledby="kh-measures" style={{ borderTop: '1px solid #1a1a1a', paddingTop: 16 }}>
          <h2 id="kh-measures" style={{ margin: '0 0 6px', color: '#fff', fontSize: 15 }}>Behind the number</h2>
          <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>Shown beside the headline, never weighted into it.</div>
          {STATES.filter((s) => m.claims_by_state?.[s]).map((s) => (
            <Row key={s} k={`Claims ${s.replace(/_/g, ' ')}`} v={m.claims_by_state[s].toLocaleString()} />
          ))}
          <Row k="Open objections" v={m.open_objections} />
          <Row k="Open proposals awaiting review" v={m.open_proposals ? `${m.open_proposals} · median ${m.open_proposal_median_days} days, oldest ${m.oldest_open_proposal_days}` : '0'} />
          <Row k="Independent reproductions" v={repro.length ? repro.map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(' · ') : 'none yet'} />
          <Row k="Operators reviewing (last 30 days)" v={m.operators_reviewing_30d} />
          <Row k="Sources" v={Object.entries(m.sources_by_provenance || {}).map(([k, v]) => `${v} ${k}`).join(' · ') || '0'} />
        </section>
      )}
      {d?.method && (
        <section aria-labelledby="kh-how" style={{ borderTop: '1px solid #1a1a1a', paddingTop: 16 }}>
          <h2 id="kh-how" style={{ margin: '0 0 8px', color: '#fff', fontSize: 15 }}>How it’s measured</h2>
          <ul style={{ margin: 0, paddingLeft: 18, color: '#999', fontSize: 13, lineHeight: 1.7 }}>
            <li>Headline: {d.method.headline}.</li>
            <li>Live claims: {d.method.live}.</li>
            <li>Checked: {d.method.checked}.</li>
            <li>Not counted: {d.method.not_counted}.</li>
            <li>History: snapshots {d.method.snapshots}.</li>
          </ul>
          <div style={{ ...mono(11), color: '#555', marginTop: 8 }}>calculation {d.method.version}</div>
        </section>
      )}
    </div>
  );
}
