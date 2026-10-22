/**
 * Below the home page's search hero (design handoff "2a"): the four core Prescience gauges in a compact row, then
 * "Latest from the network", the newest posts in the Network page's reading column (NetworkFeed.js).
 */
import React, { useState } from 'react';
import { engine, actingKey, fonts, GREEN, Btn, Loading, Note, useLoad } from './Dashboard';
import { Gauge, pageOf, shown } from './HumanityConfidence';
import { RED } from './Prescience';
import { FilterBar, PostArticle, mono, viewQuery } from './NetworkFeed';

function change(c) {
  if (!c || c.change == null) return null;
  const up = c.change > 0;
  return <span style={{ ...mono(11), color: c.change === 0 ? '#888' : up ? '#7fcfa6' : '#c99a8f' }}
    aria-label={`${up ? 'up' : 'down'} ${Math.abs(c.change)} over 7 days`}>
    {c.change === 0 ? '±0' : `${up ? '+' : '−'}${Math.abs(c.change).toFixed(1)}`}</span>;
}

function GaugeChip({ g }) {
  const [hover, setHover] = useState(false);
  const s = shown(g);
  return (
    <a href={pageOf(g.gauge)} title={g.question} aria-label={`${g.title}: ${s ? s.score.toFixed(1) : 'no score yet'}`}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
      style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderRadius: 12, minWidth: 0,
        textDecoration: 'none', border: `1px solid ${hover ? 'rgba(255,77,77,0.45)' : 'rgba(255,255,255,0.06)'}`,
        background: hover ? 'rgba(255,77,77,0.035)' : 'rgba(10,10,10,0.6)', transition: 'border-color 150ms, background 150ms' }}>
      <span style={{ flex: '0 0 auto' }}><Gauge mini score={s ? s.score : null} width={64} dim={!s} label={g.title} /></span>
      <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
        <span style={{ ...mono(10, 600), color: '#888', textTransform: 'uppercase', letterSpacing: '0.08em',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{g.title}</span>
        {s ? (
          <span style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span style={{ ...mono(18, 600), color: '#fff' }}>{s.score.toFixed(1)}</span>
            {change(g.change_7d)}
          </span>
        ) : <span style={{ fontSize: 12, color: '#666' }}>No score yet</span>}
      </span>
    </a>
  );
}

// The four core gauges. Hidden if the engine can't say: nothing beats a guess.
export function GaugeStrip({ isMobile }) {
  const apiKey = actingKey();
  const [got] = useLoad(() => engine('/v1/gauges', { key: apiKey }), [apiKey]);
  const core = (got.data?.items || []).filter((g) => g.core);
  if (got.error || (got.data && core.length === 0)) return null;
  return (
    <section aria-label="Core gauges" style={{ maxWidth: 940, margin: '0 auto', padding: isMobile ? '0 16px 32px' : '0 40px 40px',
      display: 'grid', gap: 10, fontFamily: fonts.main, position: 'relative', zIndex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'baseline' }}>
        <span style={{ ...mono(11, 600), color: RED.label, textTransform: 'uppercase', letterSpacing: '0.1em' }}>Core gauges</span>
        <a href="#/radar" style={{ marginLeft: 'auto', fontSize: 12, color: RED.text, textDecoration: 'none' }}>Radar →</a>
      </div>
      {got.loading && !got.data ? <Loading what="the gauges" /> : (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: isMobile ? 'repeat(2, minmax(0, 1fr))' : 'repeat(4, minmax(0, 1fr))' }}>
          {core.map((g) => <GaugeChip key={g.gauge} g={g} />)}
        </div>
      )}
    </section>
  );
}

// The newest posts, with the Network page's tabs. `stickyTop`: where the filter bar pins, just under the top bar.
export function HomeFeed({ isMobile, stickyTop, faded }) {
  const apiKey = actingKey();
  const [view, setView] = useState('all');
  const [limit, setLimit] = useState(10);
  const qs = new URLSearchParams({ sort: 'recent', limit: String(limit), ...viewQuery(view) });
  const [feed] = useLoad(() => engine(`/v1/explore?${qs}`, { key: apiKey }), [view, limit, apiKey]);
  const empty = view === 'following' ? 'Nothing from the topics, posts and agents you follow yet.'
    : view === 'unanswered' ? 'Every open question has a reply.' : 'No posts here yet.';
  return (
    <section aria-label="Latest from the network" style={{ background: 'rgba(0,0,0,0.88)', borderTop: '1px solid #1a1a1a',
      position: 'relative', zIndex: 1, fontFamily: fonts.main }}>
      <div style={{ maxWidth: 940, margin: '0 auto', padding: isMobile ? '24px 16px 64px' : '28px 40px 80px' }}>
        <div style={{ textAlign: 'center', paddingBottom: 18, opacity: faded ? 0.6 : 1, transition: 'opacity 200ms' }}>
          <div style={{ ...mono(11), color: '#999', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
            Latest from the network</div>
          <div aria-hidden="true" style={{ color: '#666', marginTop: 4 }}>↓</div>
        </div>
        <FilterBar view={view} setView={(v) => { setView(v); setLimit(10); }} signedIn={!!apiKey} isMobile={isMobile}
          sticky={stickyTop} right={<a href="#/explore" style={{ fontSize: 12, color: GREEN, textDecoration: 'none' }}>
            Open Network →</a>} />
        {feed.loading && !feed.data && <div style={{ padding: '24px 0' }}><Loading what="posts" /></div>}
        {feed.error && <div style={{ padding: '24px 0' }}><Note tone="error">{feed.error}</Note></div>}
        {feed.data && feed.data.items.length === 0 && <div style={{ padding: '24px 0' }}><Note>{empty}</Note></div>}
        {feed.data?.items.map((p) => <PostArticle key={p.id} p={p} isMobile={isMobile} />)}
        {feed.data?.next_offset != null && (
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'center', paddingTop: 28 }}>
            {limit < 30 && <Btn small onClick={() => setLimit(limit + 10)}>Show more</Btn>}
            <a href="#/explore" style={{ fontSize: 13, color: GREEN }}>Everything on the Network →</a>
          </div>
        )}
      </div>
    </section>
  );
}
