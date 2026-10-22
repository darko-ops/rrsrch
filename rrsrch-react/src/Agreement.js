/**
 * "How much agents agree" on a gauge's page (design handoff 5a/5b): a 0-100 strip of agent tokens under the hero.
 * With few votes each score gets its own token, one agent each in practice; with more, votes are grouped into 5-point
 * ranges (10-point on a narrow screen) and a token grows from a ring to a large filled circle as its range fills, its
 * area following the count. A band around the index marks the agreement window; tokens outside it are faded.
 *
 * Data: the gauge's index.histogram (engine: counted agents per score, 0-100, abstentions left out).
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Bot, CircleUser } from 'lucide-react';
import { bandColor, mono, useReducedMotion } from './HumanityConfidence';

export const AGREE_WINDOW = 10;            // ± points around the index that count as agreeing: a product decision
const EXACT_UP_TO = 60;                    // at or below this many votes, one token per score
const RED_LABEL = '#ff8a8a';
const PROVISIONAL = '#b9a46f';
const BASE = '#0d0d0d';
const fmt = (n) => n.toLocaleString('en-US');

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const tint = (hex, a) => { const [r, g, b] = rgb(hex); return `rgba(${r},${g},${b},${a})`; };

// The tokens for a histogram: where each sits, how big, how filled, and whether it's inside the window.
export function agreementTokens(counts, index, { stripPx = 960, window = AGREE_WINDOW } = {}) {
  const total = counts.reduce((a, b) => a + b, 0);
  const exact = total <= EXACT_UP_TO && stripPx >= 600;
  const w = exact ? 1 : stripPx < 600 ? 10 : 5;
  const bins = [];
  if (exact) {
    counts.forEach((n, s) => { if (n) bins.push({ lo: s, hi: s, centre: s, n }); });
  } else {
    const last = 100 / w - 1;               // 100 joins the top range
    const sums = new Array(100 / w).fill(0);
    counts.forEach((n, s) => { sums[Math.min(Math.floor(s / w), last)] += n; });
    sums.forEach((n, k) => { if (n) bins.push({ lo: k * w, hi: k === last ? 100 : k * w + w - 1, centre: k * w + w / 2, n }); });
  }
  const max = Math.max(0, ...bins.map((b) => b.n));
  // room before neighbours pile up, but never below one agent's 24px token
  const maxD = Math.max(24, Math.min(58, (exact ? 2 : w) * (stripPx / 100) * 1.12));
  const tokens = bins.map((b) => {
    const t = max > 1 ? Math.sqrt((b.n - 1) / (max - 1)) : 0;
    const d = Math.min(maxD, 24 + 34 * t);
    return { ...b, t, d, color: bandColor(b.centre), inside: index != null && Math.abs(b.centre - index) <= window,
      title: b.n === 1 && b.lo === b.hi ? `${b.lo} / 100`
        : `${b.lo === b.hi ? b.lo : `${b.lo}–${b.hi}`}: ${fmt(b.n)} agent${b.n === 1 ? '' : 's'}` };
  });
  const agree = index == null ? 0 : counts.reduce((a, n, s) => a + (Math.abs(s - index) <= window ? n : 0), 0);
  const unit = exact ? (bins.every((b) => b.n === 1) ? 'One token per agent.' : 'One token per score.')
    : `Agents per ${w}-point range.`;
  return { tokens, total, agree, unit };
}

// lucide's Bot without its side "ears", which crowd a small token
export function TokenBot({ size, color }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.4} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" style={{ display: 'block' }}>
      <path d="M12 8V4H8" /><rect width="16" height="12" x="4" y="8" rx="2" /><path d="M15 13v2" /><path d="M9 13v2" />
    </svg>
  );
}

export function Token({ d, t, color, n, faded, title, style }) {
  const ink = t > 0.55 ? BASE : color;
  const a = Math.pow(t, 1.3);
  return (
    <span title={title} style={{ width: d, height: d, boxSizing: 'border-box', borderRadius: 999, border: `2px solid ${color}`,
      backgroundColor: BASE, backgroundImage: `linear-gradient(${tint(color, a)}, ${tint(color, a)})`,
      display: 'grid', placeItems: 'center', alignContent: 'center', gap: 1, opacity: faded ? 0.5 : 1, ...style }}>
      <TokenBot size={Math.round(12 + 6 * t)} color={ink} />
      {d >= 38 && n != null && <span style={{ ...mono(9.5, 700), lineHeight: 1, color: ink }}>{fmt(n)}</span>}
    </span>
  );
}

function useWidth(fallback = 960) {
  const ref = useRef(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    if (el.clientWidth) setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(([e]) => { if (e.contentRect.width) setWidth(e.contentRect.width); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function Stat({ icon: Icon, n, words }) {
  return (
    <span title={words} aria-label={words} style={{ display: 'inline-flex', gap: 7, alignItems: 'center' }}>
      <Icon aria-hidden="true" size={15} strokeWidth={2} color="#8a8a8a" />
      <span aria-hidden="true" style={{ ...mono(14, 600), color: '#e5e5e5' }}>{fmt(n)}</span>
    </span>
  );
}

function Key() {
  const sample = [[24, 0, '1'], [32, Math.pow(0.2, 1 / 1.3), 'few'], [44, Math.pow(0.6, 1 / 1.3), 'many'], [58, 1, 'most']];
  return (
    <span aria-hidden="true" style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
      {sample.map(([d, t, label]) => (
        <span key={label} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <Token d={d} t={t} color="#62a883" /><span style={{ ...mono(11), color: '#888' }}>{label}</span>
        </span>
      ))}
    </span>
  );
}

// The panel. Renders nothing until someone has scored.
export default function AgreementPanel({ index, isMobile, disclaimer }) {
  const reduced = useReducedMotion();
  const [stripRef, stripPx] = useWidth(isMobile ? 340 : 960);
  const [shownIn, setShownIn] = useState(reduced);
  useEffect(() => {
    if (reduced) return undefined;
    const id = requestAnimationFrame(() => setShownIn(true));
    return () => cancelAnimationFrame(id);
  }, [reduced]);
  const counts = index?.histogram?.counts;
  if (!counts || index.score == null) return null;
  const score = index.score;
  const { tokens, total, agree, unit } = agreementTokens(counts, score, { stripPx });
  if (!total) return null;
  const W = AGREE_WINDOW;
  const zoneL = Math.max(0, score - W);
  const zoneR = Math.min(100, score + W);
  const zone = bandColor(score);
  const pct = Math.round((agree / total) * 100);
  const big = (n) => <span style={{ ...mono(14, 600), color: '#fff' }}>{fmt(n)}</span>;
  const order = [...tokens].sort((a, b) => a.centre - b.centre);
  return (
    <section aria-label="How much agents agree" style={{ background: 'rgba(10,10,10,0.75)', border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 14, padding: isMobile ? '18px 16px 14px' : '22px 26px 18px', display: 'grid', gap: 18, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: isMobile ? 10 : 16, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ ...mono(11, 600), color: RED_LABEL, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          How much agents agree{index.status === 'provisional' && <span style={{ color: PROVISIONAL }}> · provisional</span>}</span>
        <span style={{ fontSize: 14, color: '#ddd' }}>{big(agree)} of {fmt(total)} agent{total === 1 ? '' : 's'}{' '}
          (<span style={{ ...mono(14, 600), color: '#fff' }}>{pct}%</span>) {agree === 1 && total > 1 ? 'is' : 'are'} within ±{W} of
          the index</span>
        <span style={{ marginLeft: isMobile ? 0 : 'auto', display: 'inline-flex', gap: 16, ...(isMobile && { flexBasis: '100%' }) }}>
          <Stat icon={Bot} n={total} words={`${fmt(total)} agent${total === 1 ? '' : 's'}`} />
          <Stat icon={CircleUser} n={index.operators} words={`${fmt(index.operators)} operator${index.operators === 1 ? '' : 's'}`} />
        </span>
      </div>
      <div ref={stripRef} role="img" aria-label={`Agents by score: ${order.map((t) => t.title).join('; ')}. Index ${score.toFixed(1)}.`}
        style={{ position: 'relative', height: 120 }}>
        <div style={{ position: 'absolute', top: 0, bottom: 22, left: 0, right: 0, display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)' }}>
          {[0, 1, 2, 3, 4].map((k) => <span key={k} style={{ borderLeft: '1px solid #1d1d1d',
            ...(k === 4 && { borderRight: '1px solid #1d1d1d' }) }} />)}
        </div>
        <div style={{ position: 'absolute', top: 0, bottom: 22, left: `${zoneL}%`, width: `${zoneR - zoneL}%`,
          background: tint(zone, 0.08), borderLeft: `1px dashed ${tint(zone, 0.5)}`, borderRight: `1px dashed ${tint(zone, 0.5)}` }} />
        <div style={{ position: 'absolute', top: 49, left: 0, right: 0, height: 2, background: '#222' }} />
        <div style={{ position: 'absolute', top: 6, bottom: 22, left: `${score}%`, width: 2, marginLeft: -1, background: '#fff',
          zIndex: 200 }}>
          <span style={{ position: 'absolute', top: -4, left: 0, whiteSpace: 'nowrap', ...mono(10.5, 600), color: '#fff',
            transform: score > 85 ? 'translate(calc(-100% - 6px), 0)' : 'translate(6px, 0)' }}>index {score.toFixed(1)}</span>
        </div>
        {order.map((t, k) => (
          <Token key={`${t.lo}-${t.hi}`} d={t.d} t={t.t} color={t.color} n={t.n} faded={!t.inside} title={t.title}
            style={{ position: 'absolute', top: 50, left: `${t.centre}%`, zIndex: Math.round(t.d),
              transform: `translate(-50%, -50%) scale(${shownIn ? 1 : 0.6})`,
              transition: reduced ? 'none' : `transform 300ms ease-out ${k * 15}ms` }} />
        ))}
        <div aria-hidden="true" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, display: 'flex',
          justifyContent: 'space-between', ...mono(10), color: '#555' }}>
          {[0, 20, 40, 60, 80, 100].map((x) => <span key={x}>{x}</span>)}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap', borderTop: '1px solid #1a1a1a',
        paddingTop: 12, fontSize: 11.5, color: '#666' }}>
        <Key />
        <span>{unit} Hover a token for its {unit.startsWith('Agents') ? 'range' : 'score'} and count.</span>
        <span style={{ marginLeft: isMobile ? 0 : 'auto' }}>Faded tokens are outside the agreement window.</span>
        {disclaimer && <span style={{ flexBasis: '100%', color: '#555' }}>{disclaimer}</span>}
      </div>
    </section>
  );
}
