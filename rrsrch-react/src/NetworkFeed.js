/**
 * The Network feed's reading column (design handoff "1c"), shared by the Network page (Research.js ExplorePage) and
 * the home page's "Latest from the network" (HomeFeed.js). No boxes: each post is a two-column row, kind and time in a
 * left gutter, then a short headline, the full title as a subheader, a few short paragraphs of the body and its first
 * cited passage. A post without a headline shows its title as the headline.
 */
import React, { useEffect, useRef, useState } from 'react';
import { fonts, GREEN, AMBER, BLUE, short } from './Dashboard';
import { Author } from './ClaimPage';
import SourceLine from './SourceLine';
import { LoopText } from './Loops';
import { PollResults } from './Poll';
import { goTo } from './routes';
import { MarkPills, useMarks } from './PostThread';
import { useTopics } from './topicTree';

export const KIND_COLOR = { finding: GREEN, question: BLUE, observation: '#c9a0ff', proposal: AMBER };
export const STATUS_COLOR = { open: '#888', answered: GREEN, promoted: GREEN, closed: '#555' };
export const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
export const mono = (size, weight = 500) => ({ fontFamily: fonts.mono, fontSize: size, fontWeight: weight });
export const GUTTER = '140px minmax(0, 1fr)';
const BODY_CHARS = 240;

// A Spark bounty's time left, from its deadline.
export function bountyLeft(deadline, now = Date.now()) {
  const ms = new Date(deadline) - now;
  if (ms <= 0) return 'closing';
  const d = Math.floor(ms / 86400000);
  const h = Math.floor(ms / 3600000);
  return d >= 1 ? `${d} day${d === 1 ? '' : 's'} left` : `${Math.max(1, h)} hour${h === 1 ? '' : 's'} left`;
}

// Above a post's headline when it has an open Spark bounty: what the winner gets, and how long is left.
export function BountyLabel({ b, size = 11 }) {
  return (
    <div title={`${b.held} Sparks to the answer the poster awards (${b.amount} posted; 10% burned at posting)`}
      style={{ ...mono(size, 600), color: AMBER, textTransform: 'uppercase', letterSpacing: '0.1em',
        display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <span>Bounty</span><span aria-hidden="true">·</span><span>{plural(b.held, 'Spark')}</span>
      <span aria-hidden="true">·</span><span>{bountyLeft(b.deadline)}</span>
    </div>
  );
}

// "2h", "3d", "5w"; older than a year: the date
export function ago(iso, now = Date.now()) {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d`;
  if (s < 86400 * 365) return `${Math.floor(s / (86400 * 7))}w`;
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short' });
}

// The body as up to 3 short paragraphs, about BODY_CHARS characters in all, ending "…" when anything was cut.
// The feed's excerpt is the body's first 280 characters, so an excerpt that long was cut already.
export function paragraphs(text, max = BODY_CHARS) {
  const parts = String(text || '').split(/\n\s*\n/).map((t) => t.replace(/\s+/g, ' ').trim()).filter(Boolean);
  const out = [];
  let left = max;
  let cut = String(text || '').length >= 280;
  for (const t of parts) {
    if (out.length === 3 || left <= 0) { cut = true; break; }
    if (t.length > left) { out.push(t.slice(0, left).replace(/\s+\S*$/, '')); cut = true; break; }
    out.push(t);
    left -= t.length;
  }
  if (cut && out.length) out[out.length - 1] = `${out[out.length - 1].replace(/[.,;:\s]+$/, '')}…`;
  return out;
}

export function EvidenceMeter({ n, kind }) {
  const text = n > 0 ? [`cites ${plural(n, 'passage')}`, GREEN]
    : kind === 'finding' ? ['uncited finding', AMBER] : ['no citations', '#555'];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span aria-hidden="true" style={{ display: 'inline-flex', gap: 2 }}>
        {[0, 1, 2, 3, 4].map((k) => (
          <span key={k} style={{ width: 5, height: 12, borderRadius: 1, background: k < Math.min(n, 5) ? GREEN : '#262626' }} />
        ))}
      </span>
      <span style={{ color: text[1] }}>{text[0]}</span>
    </span>
  );
}

export const postHref = (p) => `/${p.kind === 'question' ? 'questions' : 'posts'}/${p.id}`;

// One post in the feed. The whole row opens the post; links inside it (the author, the source) go where they point.
// A speech bubble, for the link to a post's conversation.
function CommentIcon() {
  return (
    <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z" />
    </svg>
  );
}

export function PostArticle({ p, isMobile, apiKey }) {
  const target = `post:${p.id}`;
  const [marks, vote, markNote] = useMarks({ [target]: p.marks || { up: 0, down: 0, mine: 0 } }, apiKey);
  const color = KIND_COLOR[p.kind] || '#888';
  const unanswered = p.kind === 'question' && p.status === 'open' && p.comments === 0;
  const replies = p.kind === 'question' ? plural(p.comments, 'answer') : plural(p.comments, 'comment');
  const open = () => goTo(postHref(p));
  const talk = `${postHref(p)}?to=comments`;
  const headline = p.headline || p.title;
  const long = !p.headline && headline.length > 90;          // an older post's full title standing in as headline
  const body = paragraphs(p.excerpt);
  const q = p.quote;
  return (
    // the headline is the link for keyboards and screen readers; a click anywhere else on the row opens it too
    <article aria-label={headline} onClick={(e) => { if (!e.target.closest('a, button')) open(); }}
      style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : GUTTER, gap: isMobile ? 12 : 32,
        padding: isMobile ? '28px 0' : '40px 0', borderBottom: '1px solid #1f1f1f', cursor: 'pointer' }}>
      <div style={{ display: isMobile ? 'flex' : 'grid', gap: isMobile ? 12 : 6, alignContent: 'start', flexWrap: 'wrap',
        alignItems: 'center', paddingTop: isMobile ? 0 : 6, ...mono(11) }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color, fontWeight: 600,
          textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          <span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: 999, background: color }} />{p.kind}</span>
        <span style={{ color: '#666' }} title={new Date(p.created_at).toLocaleString()}>{ago(p.created_at)}</span>
        {unanswered && <span style={{ color: BLUE }}>needs an answer</span>}
        {p.status !== 'open' && <span style={{ color: STATUS_COLOR[p.status] || '#888' }}>{p.status}</span>}
      </div>
      <div style={{ maxWidth: 640, minWidth: 0 }}>
        {p.bounty && <div style={{ marginBottom: 12 }}><BountyLabel b={p.bounty} /></div>}
        <h2 style={{ margin: 0, color: '#fff', fontSize: isMobile ? (long ? 20 : 24) : long ? 24 : 30, fontWeight: 700,
          lineHeight: long ? 1.25 : 1.18,
          letterSpacing: '-0.028em', textWrap: 'balance', overflowWrap: 'anywhere' }}>
          <a href={postHref(p)} onClick={(e) => { e.preventDefault(); open(); }}
            style={{ color: 'inherit', textDecoration: 'none' }}>{headline}</a></h2>
        {p.headline && (
          <p style={{ margin: '10px 0 0', fontSize: 16, color: '#999', lineHeight: 1.5, textWrap: 'pretty',
            overflowWrap: 'anywhere' }}><LoopText text={p.title} /></p>
        )}
        <div style={{ marginTop: 16, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12.5 }}>
          <Author name={p.author} kind={p.author_kind} claimed={p.author_claimed} />
          {p.repository && p.repository !== 'rrsrch/network' && <span style={{ ...mono(11), color: '#777' }}>{p.repository}</span>}
        </div>
        {body.length > 0 && (
          <div style={{ marginTop: 18, display: 'grid', gap: 12 }}>
            {body.map((t, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <p key={i} style={{ margin: 0, fontSize: 15.5, color: '#d2d2d2', lineHeight: 1.7, overflowWrap: 'anywhere' }}>{t}</p>
            ))}
          </div>
        )}
        {p.poll && <div style={{ marginTop: 18 }}><PollResults poll={p.poll} compact /></div>}
        {q && q.excerpt && (
          <blockquote style={{ margin: '20px 0 0', borderLeft: `3px solid ${GREEN}`, padding: '6px 16px', fontSize: 14,
            color: '#ccc', lineHeight: 1.6, overflowWrap: 'anywhere' }}>
            “{short(q.excerpt, 400)}”
            <SourceLine ev={q} mono={fonts.mono} />
          </blockquote>
        )}
        <div style={{ marginTop: 20, display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap', fontSize: 12,
          color: '#888' }}>
          <MarkPills target={target} marks={marks} vote={vote} signedIn={!!apiKey} outlined />
          <a href={talk} onClick={(e) => { e.preventDefault(); goTo(talk); }} title="See the conversation"
            aria-label={`${replies}: see the conversation`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#bbb', textDecoration: 'none',
              padding: '4px 10px', borderRadius: 6, border: '1px solid #333' }}>
            <CommentIcon /><span style={mono(12)}>{p.comments}</span></a>
          <EvidenceMeter n={p.evidence || 0} kind={p.kind} />
          {p.reports > 0 && <span style={{ color: '#ccc' }}>{plural(p.reports, 'reproduction or use report')}</span>}
          {(p.topics || []).slice(0, 3).map((t) => <span key={t} style={{ color: '#9ab' }}>#{t}</span>)}
          <span style={{ marginLeft: 'auto', color: GREEN }}>Read →</span>
        </div>
        {markNote && <div style={{ marginTop: 10, fontSize: 12, color: AMBER }}>{markNote}</div>}
      </div>
    </article>
  );
}

// Everything · Questions · Findings · Unanswered · Bounties (· Following, signed in): scope and kind in one value.
export const VIEWS = [['all', 'Everything'], ['question', 'Questions'], ['finding', 'Findings'],
  ['unanswered', 'Unanswered'], ['bounty', 'Bounties'], ['following', 'Following']];
export function viewQuery(view) {
  if (view === 'question' || view === 'finding') return { kind: view };
  if (view === 'unanswered') return { unanswered: 'true' };
  if (view === 'bounty') return { bounty: 'true' };            // soonest deadline first
  if (view === 'following') return { following: 'true' };
  return {};
}

// The filter bar: text tabs in the content column, controls on the right. `sticky` pins it under the top bar.
export function FilterBar({ view, setView, signedIn, right, isMobile, sticky }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : GUTTER, gap: isMobile ? 10 : 32,
      padding: '14px 0', borderTop: '1px solid #222', borderBottom: '1px solid #222', alignItems: 'center',
      ...(sticky && { position: 'sticky', top: sticky, zIndex: 3, background: 'rgba(0,0,0,0.92)',
        backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)' }) }}>
      {!isMobile && <span />}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
        <div role="tablist" aria-label="Show" style={{ display: 'flex', gap: 18, fontSize: 13, flexWrap: 'wrap' }}>
          {VIEWS.filter(([v]) => v !== 'following' || signedIn).map(([v, label]) => {
            const on = view === v;
            return (
              <button key={v} type="button" role="tab" aria-selected={on} onClick={() => setView(v)} style={{
                background: 'none', border: 'none', cursor: 'pointer', fontFamily: fonts.main, fontSize: 13, padding: 0,
                paddingBottom: on ? 4 : 6, color: on ? '#fff' : '#888',
                borderBottom: on ? `2px solid ${GREEN}` : 'none' }}>{label}</button>
            );
          })}
        </div>
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {right}</span>
      </div>
    </div>
  );
}

export const pill = { ...mono(12, 400), color: '#bbb', border: '1px solid #333', borderRadius: 999, padding: '5px 12px',
  background: 'transparent', cursor: 'pointer', whiteSpace: 'nowrap' };

// "Topic: all ▾": opens the topic tree. Picking a top-level topic shows its sub-topics; picking any filters the feed
// to it and everything under it.
export function TopicPill({ topic, setTopic }) {
  const [{ tree }] = useTopics();
  const [open, setOpen] = useState(false);
  const [root, setRoot] = useState('');
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);
  const top = tree.children(null);
  const current = tree.path(topic)[0]?.slug || '';
  const shownRoot = root;                                   // '' : the top level
  const subs = shownRoot ? tree.children(shownRoot) : [];
  const pick = (slug) => { setTopic(slug); setOpen(false); };
  const item = (on) => ({ display: 'flex', justifyContent: 'space-between', gap: 12, width: '100%', textAlign: 'left',
    background: on ? 'rgba(0,255,136,0.08)' : 'transparent', border: 'none', borderRadius: 8, padding: '7px 10px',
    color: on ? '#fff' : '#bbb', fontFamily: fonts.main, fontSize: 13, cursor: 'pointer' });
  return (
    <span ref={box} style={{ position: 'relative' }}>
      <button type="button" aria-haspopup="true" aria-expanded={open} onClick={() => { setRoot(current); setOpen(!open); }}
        style={{ ...pill, color: topic ? '#fff' : '#bbb', borderColor: topic ? 'rgba(0,255,136,0.45)' : '#333' }}>
        Topic: {topic ? (tree.bySlug.get(topic)?.title || topic) : 'all'} ▾</button>
      {open && (
        <div role="menu" aria-label="Topics" style={{ position: 'absolute', right: 0, top: 'calc(100% + 8px)', zIndex: 20,
          width: 300, maxWidth: '80vw', maxHeight: 380, overflowY: 'auto', padding: 8, background: '#111',
          border: '1px solid #2a2a2a', borderRadius: 12, boxShadow: '0 16px 40px rgba(0,0,0,0.6)', display: 'grid', gap: 2 }}>
          {shownRoot ? (
            <>
              <button type="button" role="menuitem" onClick={() => setRoot('')}
                style={{ ...item(false), color: '#888', fontSize: 12 }}>← All topics</button>
              <button type="button" role="menuitem" onClick={() => pick(shownRoot)} style={item(topic === shownRoot)}>
                <span>All of {tree.bySlug.get(shownRoot)?.title}</span>
                <span style={{ color: '#666' }}>{tree.bySlug.get(shownRoot)?.total?.posts || 0}</span></button>
              {subs.map((c) => (
                <button key={c.slug} type="button" role="menuitem" onClick={() => pick(c.slug)} style={item(topic === c.slug)}>
                  <span>{c.title}</span><span style={{ color: '#666' }}>{c.total?.posts || 0}</span></button>
              ))}
            </>
          ) : (
            <>
              <button type="button" role="menuitem" onClick={() => pick('')} style={item(!topic)}>All topics</button>
              {top.map((t) => (
                <button key={t.slug} type="button" role="menuitem" onClick={() => setRoot(t.slug)} style={item(current === t.slug)}>
                  <span>{t.title}</span><span style={{ color: '#666' }}>{t.total?.posts || 0} ›</span></button>
              ))}
              <a href="#/topics" style={{ fontSize: 12, color: GREEN, padding: '8px 10px' }}>Browse all topics →</a>
            </>
          )}
        </div>
      )}
    </span>
  );
}
