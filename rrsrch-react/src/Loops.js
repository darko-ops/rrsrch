/**
 * Loops (engine serve/onboarding.md, section 4): a post connects to other posts by naming them: #N, or in words,
 * "post 61", "posts 61 and 62", "question 52", "post:25". They read like an article's citations: LoopText turns
 * each into a link to that post with its reference number, and LoopList is the References card, the posts this one
 * loops in the order it names them and the posts that loop it, from the engine's `loops` on GET /v1/posts/N.
 */
import React from 'react';
import { fonts } from './Dashboard';
import { goTo } from './routes';

const postHref = (p) => `/${p.kind === 'question' ? 'questions' : 'posts'}/${p.id}`;

// the engine's rules (research.LOOP, NOT_A_POST, NAMED): #N not inside a word, a URL fragment or an HTML entity,
// and not naming something else, such as "MR #5"; in words, a plain "post 2008" is a year and "post 3 findings" a
// count
const LOOP = /(?<![\w&/#])#(\d{1,18})(?!\w)/g;
const NOT_A_POST = /\b(?:mr|merge request|pull request|pr|issue|claim)\s*$/i;
const NAMED = new RegExp('(?<![\\w-])(?:posts?|questions?|findings?)(\\s*:\\s*|\\s+(?:no\\.?\\s*)?#?|\\s*#)'
  + '(\\d{1,18}(?:\\s*(?:,\\s*(?:and\\s+)?|and\\s+|&\\s*)#?\\d{1,18})*)(?![\\w-])'
  + '(?![ \\t]+(?:new[ \\t]+|more[ \\t]+)?(?:posts?|questions?|findings?|answers?|comments?|replies|days?|hours?|'
  + 'minutes?|weeks?|months?|years?|times|more|others?|of)\\b)', 'gi');
const NUMBER = /(#?)(\d{1,18})/g;

// [start, end, id] for each post `text` names; words only where `named` (a post page, where the engine confirms them)
function spans(text, named) {
  const out = [];
  for (const m of text.matchAll(LOOP)) {
    if (!NOT_A_POST.test(text.slice(Math.max(0, m.index - 20), m.index))) out.push([m.index, m.index + m[0].length, Number(m[1])]);
  }
  if (named) {
    for (const m of text.matchAll(NAMED)) {
      const list = m.index + m[0].length - m[2].length;
      [...m[2].matchAll(NUMBER)].forEach((n, i) => {
        const marked = n[1] || (i === 0 && /[#:]/.test(m[1]));
        if (!marked && n[2].length === 4 && Number(n[2]) >= 1900 && Number(n[2]) <= 2099) return;
        const end = list + n.index + n[0].length;
        out.push([i === 0 ? m.index : list + n.index, end, Number(n[2])]);   // "post 61": the words link too
      });
    }
  }
  out.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  return out.filter((s, i) => !out.slice(0, i).some((t) => s[0] < t[1]));     // "question #52" once, not twice
}

const open = (href) => (e) => {
  if (e.metaKey || e.ctrlKey || e.shiftKey) return;     // let the browser open a new tab
  e.preventDefault();
  e.stopPropagation();                                  // a feed row opens its own post on click
  goTo(href);
};

// `refs`, when given, is the posts the engine looped, in reference order (a post page): those are linked, words
// included, with their reference number, and any other #N, like "the #1 cause", stays text. Without it (comments,
// feed rows), each #N is linked.
export function LoopText({ text, refs }) {
  if (!text) return text ?? null;
  const number = refs && new Map(refs.map((p, i) => [p.id, i + 1]));
  const out = [];
  let last = 0;
  for (const [start, end, id] of spans(text, !!refs)) {
    if (number && !number.has(id)) continue;
    if (start > last) out.push(text.slice(last, start));
    const href = `/posts/${id}`;
    out.push(
      <a key={start} href={href} onClick={open(href)} title={`Open post ${id}`}
        style={{ color: '#9ab', textDecoration: 'none', background: 'rgba(153,170,187,0.12)', borderRadius: 5,
          padding: '0 4px' }}>
        {text.slice(start, end)}
        {number && <sup style={{ fontFamily: fonts.mono, fontSize: '0.62em', marginLeft: 2 }}>[{number.get(id)}]</sup>}
      </a>,
    );
    last = end;
  }
  if (!out.length) return text;
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

export function LoopRow({ p, n }) {
  const href = postHref(p);
  return (
    <li style={{ listStyle: 'none' }}>
      <a href={href} onClick={open(href)} style={{ display: 'flex', gap: 12, alignItems: 'baseline', padding: '10px 12px',
        borderRadius: 10, border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.025)',
        textDecoration: 'none', minWidth: 0 }}>
        <span style={{ fontFamily: fonts.mono, fontSize: 12, color: '#9ab', flex: 'none', minWidth: 26 }}>
          {n ? `[${n}]` : '↩'}</span>
        <span style={{ display: 'grid', gap: 3, minWidth: 0 }}>
          <span style={{ color: '#e6e6e6', fontSize: 14, lineHeight: 1.45, overflowWrap: 'anywhere' }}>{p.headline || p.title}</span>
          <span style={{ color: '#777', fontSize: 12 }}>{p.kind} by {p.author} · #{p.id}</span>
        </span>
        <span aria-hidden style={{ marginLeft: 'auto', color: '#666', flex: 'none' }}>→</span>
      </a>
    </li>
  );
}

// The References card: what this post loops, numbered as its text cites them, and what loops it
export function LoopList({ loops, label }) {
  const out = loops?.out || [];
  const back = loops?.in || [];
  if (!out.length && !back.length) return null;
  const group = (title, items, numbered) => items.length > 0 && (
    <section aria-label={title} style={{ display: 'grid', gap: 6 }}>
      <div style={label}>{title}</div>
      <ol style={{ margin: 0, padding: 0, display: 'grid', gap: 6, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        {items.map((p, i) => <LoopRow key={p.id} p={p} n={numbered ? i + 1 : null} />)}
      </ol>
    </section>
  );
  return (
    <div id="references" style={{ display: 'grid', gap: 16, gridTemplateColumns: 'minmax(0, 1fr)', scrollMarginTop: 130 }}>
      {group(`References · loops ${out.length} ${out.length === 1 ? 'post' : 'posts'}`, out, true)}
      {group(`Referenced by ${back.length} ${back.length === 1 ? 'post' : 'posts'}`, back, false)}
    </div>
  );
}

// a line near a post's title: how many posts it references and is referenced by, jumping to the References card
export function LoopCount({ loops }) {
  const out = loops?.out?.length || 0;
  const back = loops?.in?.length || 0;
  if (!out && !back) return null;
  const parts = [out && `${out} ${out === 1 ? 'reference' : 'references'}`, back && `referenced by ${back}`].filter(Boolean);
  return (
    <a href="#references" onClick={(e) => { e.preventDefault(); document.getElementById('references')?.scrollIntoView({ behavior: 'smooth' }); }}
      style={{ fontFamily: fonts.mono, fontSize: 12, color: '#9ab', textDecoration: 'none' }}>↻ {parts.join(' · ')}</a>
  );
}
