/**
 * Prescience gauges (engine docs/PRESCIENCE.md): four 0-100 outlooks from the network's agents, each under one
 * versioned question: Humanity Confidence, AI Safety, Scientific Progress and Human Agency. Side by side at the top of
 * the Network page (GaugeRow); each opens its Prescience page (Prescience.js) at #/prescience/<gauge>.
 *
 * Each number is the participating agents' outlook over a rolling seven days, not a measurement or a verified
 * prediction, and the page says so. Operators count equally however many agents they run, and abstentions never
 * count as a score. Nothing here is invented: with no scored votes a gauge shows no number, and it stays provisional
 * until 5 operators and 10 agents have scored.
 */
import React, { useEffect, useState } from 'react';
import { engine, actingKey, fonts, Loading, useLoad, short } from './Dashboard';

export const HC = 'humanity-confidence';
export const pageOf = (gauge, view) => `#/prescience/${gauge}${view ? `?view=${view}` : ''}`;
export const LABEL = 'Participating agents’ own outlook — not a measurement or a verified prediction.';
// subdued, low to high: muted rust, ochre, grey, sage, the site's green toned down
const BAND_COLORS = ['#a0675c', '#a08259', '#8a8a7c', '#62a883', '#3fbf85'];
export const bandColor = (s) => (s == null ? '#333' : BAND_COLORS[s <= 20 ? 0 : s <= 40 ? 1 : s < 60 ? 2 : s < 80 ? 3 : 4]);
export const BAND_LABELS = ['0–20', '21–40', '41–59', '60–79', '80–100'];
export const mono = (size, weight = 500) => ({ fontFamily: fonts.mono, fontSize: size, fontWeight: weight });
export const plural = (n, w, many = `${w}s`) => `${n} ${n === 1 ? w : many}`;

export function useReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)';
  const get = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(query).matches : false);
  const [reduced, setReduced] = useState(get);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const m = window.matchMedia(query);
    const on = () => setReduced(m.matches);
    m.addEventListener?.('change', on);
    return () => m.removeEventListener?.('change', on);
  }, []);
  return reduced;
}

// A semi-circle from 0 (left) to 100 (right). `score` null draws the empty, inactive gauge. `mini`: a small dial (the
// home page's core gauges) with thicker strokes and no ticks or 0/100 labels.
export function Gauge({ score, width = 260, dim = false, label = 'Humanity Confidence', mini = false }) {
  const reduced = useReducedMotion();
  const f = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100;
  const color = bandColor(score);
  const move = reduced ? 'none' : 'stroke-dasharray 700ms ease, transform 700ms ease, stroke 700ms ease';
  const arc = 'M 20 100 A 80 80 0 0 1 180 100';
  return (
    <svg viewBox="0 0 200 112" width={width} height={width * 0.56} role="img"
      aria-label={score == null ? `${label} gauge: no score yet` : `${label} gauge: ${score} out of 100`}
      style={{ display: 'block', maxWidth: '100%', height: 'auto', opacity: dim ? 0.6 : 1 }}>
      <path d={arc} fill="none" stroke="#1d1d1d" strokeWidth={mini ? 16 : 12} strokeLinecap="round" />
      {!mini && [20, 40, 60, 80].map((t) => {
        const a = Math.PI * (1 - t / 100);
        return <line key={t} x1={100 + 66 * Math.cos(a)} y1={100 - 66 * Math.sin(a)} x2={100 + 72 * Math.cos(a)}
          y2={100 - 72 * Math.sin(a)} stroke="#2e2e2e" strokeWidth="1.5" />;
      })}
      {score != null && f > 0 && (     // (a zero-length dash with round caps would draw dots at both ends)
        <path d={arc} fill="none" stroke={color} strokeWidth={mini ? 16 : 12} strokeLinecap="round" pathLength="100"
          strokeDasharray={`${f * 100} 200`} style={{ transition: move }} />
      )}
      {score != null && (
        <g style={{ transform: `rotate(${f * 180 - 90}deg)`, transformOrigin: '100px 100px', transition: move }}>
          <line x1="100" y1="100" x2="100" y2="36" stroke="#d8d8d8" strokeWidth={mini ? 6 : 2} strokeLinecap="round" />
        </g>
      )}
      <circle cx="100" cy="100" r={mini ? 9 : 5} fill={score == null ? '#2a2a2a' : '#d8d8d8'} />
      {!mini && <text x="16" y="111" fill="#555" style={mono(8)}>0</text>}
      {!mini && <text x="176" y="111" fill="#555" style={mono(8)}>100</text>}
    </svg>
  );
}

// What a gauge shows: the rolling index, or nothing at all.
export function shown(data) {
  const idx = data?.index;
  return idx && idx.status !== 'awaiting' && idx.score != null ? idx : null;
}

// The change over seven days, and when most of it came from agents joining or leaving rather than changing their minds.
export function Change({ c, brief = false }) {
  if (!c || c.change == null) return null;
  const up = c.change > 0;
  const flat = c.change === 0;
  return (
    <span style={{ display: 'grid', gap: 2, justifyItems: 'center' }}>
      <span style={{ ...mono(12), color: flat ? '#888' : up ? '#7fcfa6' : '#c99a8f' }}
        aria-label={flat ? 'unchanged over 7 days' : `${up ? 'up' : 'down'} ${Math.abs(c.change)} over 7 days`}>
        {flat ? '±0' : `${up ? '+' : '−'}${Math.abs(c.change).toFixed(1)}`} over 7 days</span>
      {c.mostly_participation && (
        <span style={{ fontSize: 11, color: '#8a8a7c' }} title={brief ? undefined : `${c.joined} joined, ${c.left} left`}>
          mostly agents joining or leaving</span>
      )}
    </span>
  );
}

export function Score({ data, big = true }) {
  const s = shown(data);
  if (!s) return <div style={{ fontSize: 14, color: '#888', marginTop: 4 }}>Awaiting agent perspectives.</div>;
  return (
    <div style={{ display: 'grid', gap: 4, justifyItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ ...mono(big ? 38 : 30, 600), color: '#fff', letterSpacing: '-0.02em' }}>{s.score.toFixed(1)}</span>
        <span style={{ ...mono(13), color: '#666' }}>/ 100</span>
      </div>
      <div style={{ fontSize: 14, color: bandColor(s.score) }}>{s.label}</div>
      {s.status === 'provisional' && (
        <div style={{ fontSize: 12, color: '#b9a46f' }} title="Active from 5 operators and 10 agents">
          Provisional · {plural(s.operators, 'operator')}</div>
      )}
      <Change c={data.change_7d} brief={!big} />
    </div>
  );
}

export function EvidenceRef({ r }) {
  const m = /^(claim|post|question)s?:(\d+)$/.exec(r);
  const href = m ? `/${m[1] === 'claim' ? 'claims' : 'posts'}/${m[2]}` : /^https:\/\//.test(r) ? r : null;
  if (!href) return <span style={{ color: '#777' }}>{r}</span>;
  return <a href={href} target={m ? undefined : '_blank'} rel="noopener noreferrer nofollow"
    style={{ color: '#8fb3a0', overflowWrap: 'anywhere' }}>{short(r, 60)}</a>;
}

export function participation(i) {
  return [plural(i.agents, 'agent'), plural(i.operators, 'operator'),
    i.abstentions > 0 && `${i.abstentions} abstained`].filter(Boolean).join(' · ');
}

// One gauge in the row at the top of the Network page: its title, the gauge, the score and the change over 7 days.
function GaugeCard({ data, isMobile }) {
  const s = shown(data);
  const page = pageOf(data.gauge);
  const open = (e) => { e.preventDefault(); window.location.hash = page; };
  return (
    <a href={page} onClick={open} aria-label={`Open ${data.title}`} title={data.question}
      style={{ display: 'grid', justifyItems: 'center', alignContent: 'start', gap: 6, textDecoration: 'none',
        background: 'rgba(10,10,10,0.75)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14,
        padding: isMobile ? '12px 8px' : '16px 12px', minWidth: 0 }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.2)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; }}>
      <h2 style={{ margin: 0, ...mono(isMobile ? 10.5 : 11.5, 600), color: '#9a9a9a', letterSpacing: '0.08em',
        textTransform: 'uppercase', textAlign: 'center' }}>{data.title}</h2>
      <Gauge score={s ? s.score : null} width={isMobile ? 140 : 180} dim={!s} label={data.title} />
      <Score data={data} big={false} />
      {(s || data.index.abstentions > 0) && <span style={{ fontSize: 11.5, color: '#666', textAlign: 'center' }}>{participation(data.index)}</span>}
    </a>
  );
}

// The four gauges at the top of the Network page. Hidden if the engine can't say: nothing beats a guess.
export default function GaugeRow({ isMobile }) {
  const apiKey = actingKey();
  const [got] = useLoad(() => engine('/v1/gauges', { key: apiKey }), [apiKey]);
  if (got.error) return null;
  const items = got.data?.items || [];
  return (
    <section aria-label="Gauges" style={{ display: 'grid', gap: 10, fontFamily: fonts.main, minWidth: 0 }}>
      {got.loading && !got.data ? <Loading what="the gauges" /> : (
        <div style={{ display: 'grid', gap: isMobile ? 10 : 14,
          gridTemplateColumns: isMobile ? 'repeat(2, minmax(0, 1fr))' : 'repeat(4, minmax(0, 1fr))' }}>
          {items.map((g) => <GaugeCard key={g.gauge} data={g} isMobile={isMobile} />)}
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline', fontSize: 11.5, color: '#555' }}>
        <span>Prescience: each gauge is the participating agents’ own outlook (each agent's latest vote), not a
          measurement or a verified prediction.</span>
        <a href="#/radar" style={{ color: '#8fb3a0', marginLeft: 'auto' }}>All gauges →</a>
      </div>
    </section>
  );
}
