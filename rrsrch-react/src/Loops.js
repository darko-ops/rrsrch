/**
 * Loops (engine serve/onboarding.md, section 4): a post connects to other posts by writing @#N in its headline,
 * title or body. LoopText turns each @#N in a text into a link to post N; LoopList shows a post's loops both ways,
 * the posts it loops and the posts that loop it, from the engine's `loops` on GET /v1/posts/N.
 */
import React from 'react';
import { fonts } from './Dashboard';
import { goTo } from './routes';

const postHref = (p) => `/${p.kind === 'question' ? 'questions' : 'posts'}/${p.id}`;

// the engine's pattern: @#N not glued to a word or another @, and not followed by more letters or digits
const LOOP = /(?<![\w@])@#(\d{1,18})(?!\w)/g;

const open = (href) => (e) => {
  if (e.metaKey || e.ctrlKey || e.shiftKey) return;     // let the browser open a new tab
  e.preventDefault();
  e.stopPropagation();                                  // a feed row opens its own post on click
  goTo(href);
};

export function LoopText({ text }) {
  if (!text) return text ?? null;
  const out = [];
  let last = 0;
  for (const m of text.matchAll(LOOP)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const href = `/posts/${m[1]}`;
    out.push(
      <a key={m.index} href={href} onClick={open(href)} title={`Open post ${m[1]}`}
        style={{ color: '#9ab', fontFamily: fonts.mono, fontSize: '0.92em', textDecoration: 'none',
          background: 'rgba(153,170,187,0.12)', borderRadius: 5, padding: '0 4px' }}>@#{m[1]}</a>,
    );
    last = m.index + m[0].length;
  }
  if (!out.length) return text;
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

function LoopRow({ p }) {
  const href = postHref(p);
  return (
    <a href={href} onClick={open(href)} style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '8px 12px',
      borderRadius: 10, border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.025)',
      textDecoration: 'none', minWidth: 0 }}>
      <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#9ab', flex: 'none' }}>@#{p.id}</span>
      <span style={{ color: '#e6e6e6', fontSize: 13.5, lineHeight: 1.45, overflowWrap: 'anywhere', minWidth: 0 }}>
        {p.headline || p.title}
        <span style={{ color: '#777', fontSize: 12 }}> · {p.kind} by {p.author}</span>
      </span>
    </a>
  );
}

export function LoopList({ loops, label }) {
  const out = loops?.out || [];
  const back = loops?.in || [];
  if (!out.length && !back.length) return null;
  const group = (title, items) => items.length > 0 && (
    <div style={{ display: 'grid', gap: 6, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={label}>{title}</div>
      {items.map((p) => <LoopRow key={p.id} p={p} />)}
    </div>
  );
  return (
    <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)', marginTop: 18 }}>
      {group(out.length === 1 ? 'Loops 1 post' : `Loops ${out.length} posts`, out)}
      {group(back.length === 1 ? 'Looped by 1 post' : `Looped by ${back.length} posts`, back)}
    </div>
  );
}
