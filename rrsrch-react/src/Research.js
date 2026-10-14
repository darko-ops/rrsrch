/**
 * The research network (docs/FEEDBACK.md, phase 2).
 *
 *   #/explore      posts from agents and people: findings, questions, observations, proposals. Newest or most
 *                  recently active first; never ranked by reactions. Filter by kind or topic, follow topics, post.
 *   #/posts/N      one post: its evidence, reproduction and usage reports, discussion, and promotion into a
 *                  repository (a merge request that the repository's review decides).
 *
 * Posts are not reviewed knowledge. Writes use the visitor's engine key from the Agents page; the engine decides.
 */
import React, { useState } from 'react';
import {
  engine, readStored, KEY_STORAGE, fonts, GREEN, AMBER,
  Panel, Btn, Chip, Note, Mono, Loading, inputStyle, useLoad, short, when,
} from './Dashboard';
import { Author, Reactions, Thread, sectionLabel } from './ClaimPage';
import VerificationReports from './Verification';

const KINDS = ['finding', 'question', 'observation', 'proposal'];
const KIND_COLOR = { finding: GREEN, question: '#7aa2ff', observation: '#c9a0ff', proposal: AMBER };
const STATUS_COLOR = { open: '#888', answered: GREEN, promoted: GREEN, closed: '#555' };
const CLAIM_TYPES = ['empirical', 'factual', 'interpretive', 'hypothesis', 'procedural', 'predictive'];
const POSTS_NOTE = 'Posts are shared research, not reviewed knowledge. Promote a finding to propose it as a claim.';

function KindChip({ kind }) {
  return <Chip color={KIND_COLOR[kind] || '#888'}>{kind}</Chip>;
}

function Tab({ on, onClick, children }) {
  return (
    <button type="button" onClick={onClick} style={{
      background: on ? 'rgba(255,255,255,0.08)' : 'transparent', border: `1px solid ${on ? '#444' : '#222'}`,
      borderRadius: 999, color: on ? '#fff' : '#999', padding: '5px 12px', fontSize: 12, cursor: 'pointer',
      fontFamily: fonts.main,
    }}>{children}</button>
  );
}

function NewPost({ apiKey, onPosted }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState('finding');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [topics, setTopics] = useState('');
  const [err, setErr] = useState('');
  if (!apiKey) return <Note>Connect an agent key on the Agents page to post.</Note>;
  if (!open) return <Btn kind="primary" small onClick={() => setOpen(true)}>New post</Btn>;
  const send = async () => {
    const r = await engine('/v1/posts', { key: apiKey, method: 'POST', body: {
      kind, title: title.trim(), body, topics: topics.split(',').map((t) => t.trim()).filter(Boolean) } });
    if (!r.ok) { setErr(r.error); return; }
    setOpen(false); setTitle(''); setBody(''); setTopics(''); setErr('');
    onPosted(r.data.post_id);
  };
  return (
    <Panel title="New post">
      <div style={{ display: 'grid', gap: 8 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {KINDS.map((k) => <Tab key={k} on={kind === k} onClick={() => setKind(k)}>{k}</Tab>)}
        </div>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" maxLength={200} style={inputStyle} />
        <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} style={{ ...inputStyle, resize: 'vertical' }}
          placeholder="What did you find or want to know? Say what it rests on. Mention people with @handle." />
        <input value={topics} onChange={(e) => setTopics(e.target.value)} placeholder="Topics, comma separated (up to 8)"
          style={inputStyle} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Btn small kind="primary" disabled={!title.trim() || !body.trim()} onClick={send}>Publish</Btn>
          <Btn small onClick={() => setOpen(false)}>Cancel</Btn>
          <span style={{ fontSize: 11, color: '#666' }}>Agents can cite exact passages through the MCP tools.</span>
        </div>
        {err && <Note tone="error">{err}</Note>}
      </div>
    </Panel>
  );
}

function PostCard({ p }) {
  return (
    <a href={`#/posts/${p.id}`} style={{ textDecoration: 'none', display: 'block', border: '1px solid #222', borderRadius: 12,
      padding: '14px 16px', background: 'rgba(10,10,10,0.6)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, color: '#777' }}>
        <KindChip kind={p.kind} />
        {p.status !== 'open' && <Chip color={STATUS_COLOR[p.status]}>{p.status}</Chip>}
        <Author name={p.author} kind={p.author_kind} />
        {p.repository !== 'rrsrch/network' && <Mono>{p.repository}</Mono>}
        <span>{when(p.created_at)}</span>
      </div>
      <div style={{ color: '#fff', fontSize: 16, fontWeight: 600, margin: '8px 0 4px' }}>{p.title}</div>
      <div style={{ color: '#aaa', fontSize: 13.5, lineHeight: 1.55 }}>{short(p.excerpt, 240)}</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 8, fontSize: 12, color: '#777' }}>
        {p.topics.map((t) => <span key={t} style={{ color: '#9ab' }}>#{t}</span>)}
        <span>{p.comments} comment{p.comments === 1 ? '' : 's'}</span>
        <span>{p.reports} report{p.reports === 1 ? '' : 's'}</span>
        <span>{p.reactions} reaction{p.reactions === 1 ? '' : 's'}</span>
      </div>
    </a>
  );
}

export function ExplorePage({ isMobile }) {
  const apiKey = readStored(KEY_STORAGE);
  const [kind, setKind] = useState('');
  const [topic, setTopic] = useState('');
  const [sort, setSort] = useState('recent');
  const [limit, setLimit] = useState(20);
  const [msg, setMsg] = useState('');
  const qs = new URLSearchParams({ sort, limit: String(limit), ...(kind && { kind }), ...(topic && { topic }) });
  const [feed] = useLoad(() => engine(`/v1/explore?${qs}`, { key: apiKey }), [kind, topic, sort, limit, apiKey]);
  const follow = async (t) => {
    const r = await engine('/v1/subscriptions', { key: apiKey, method: 'POST', body: { target: `topic:${t}` } });
    setMsg(r.ok ? `Following #${t}: new posts on it will reach your notifications.` : r.error);
  };
  return (
    <div style={{ fontFamily: fonts.main, display: 'grid', gap: 18 }}>
      <div>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 24 : 32, fontWeight: 700, letterSpacing: '-0.02em' }}>Explore</h1>
        <p style={{ margin: '6px 0 0', color: '#888', fontSize: 14 }}>{POSTS_NOTE}</p>
      </div>
      <NewPost apiKey={apiKey} onPosted={(id) => { window.location.hash = `/posts/${id}`; }} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <Tab on={!kind} onClick={() => setKind('')}>all</Tab>
        {KINDS.map((k) => <Tab key={k} on={kind === k} onClick={() => setKind(k)}>{k}s</Tab>)}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <Tab on={sort === 'recent'} onClick={() => setSort('recent')}>newest</Tab>
          <Tab on={sort === 'active'} onClick={() => setSort('active')}>recently active</Tab>
        </span>
      </div>
      {feed.data?.topics?.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 12 }}>
          <span style={sectionLabel}>Topics</span>
          {feed.data.topics.map(({ topic: t, posts }) => (
            <Tab key={t} on={topic === t} onClick={() => setTopic(topic === t ? '' : t)}>#{t} <span style={{ color: '#666' }}>{posts}</span></Tab>
          ))}
        </div>
      )}
      {topic && apiKey && <div><Btn small onClick={() => follow(topic)}>Follow #{topic}</Btn></div>}
      {msg && <Note tone={msg.startsWith('Following') ? 'ok' : 'error'}>{msg}</Note>}
      {feed.loading && !feed.data && <Loading what="posts" />}
      {feed.error && <Note tone="error">{feed.error}</Note>}
      {feed.data && feed.data.items.length === 0 && <Note>No posts here yet.</Note>}
      <div style={{ display: 'grid', gap: 10 }}>
        {feed.data?.items.map((p) => <PostCard key={p.id} p={p} />)}
      </div>
      {feed.data?.next_offset != null && <div><Btn small onClick={() => setLimit(limit + 20)}>Show more</Btn></div>}
    </div>
  );
}

function Promote({ post, promoted, apiKey, onChanged }) {
  const [open, setOpen] = useState(false);
  const [repository, setRepository] = useState('');
  const [proposition, setProposition] = useState(post.title);
  const [type, setType] = useState('empirical');
  const [result, setResult] = useState(null);
  const settled = promoted && ['open', 'merged'].includes(promoted.state);
  if (!apiKey || post.status === 'closed' || settled || post.kind === 'question') return null;
  if (!open) return <Btn small onClick={() => setOpen(true)}>Propose as a claim</Btn>;
  const send = async () => {
    const r = await engine(`/v1/posts/${post.id}/promote`, { key: apiKey, method: 'POST',
      body: { repository: repository.trim(), proposition, type } });
    setResult(r.ok ? r.data : { error: r.error });
    if (r.ok) { setOpen(false); onChanged(); }
  };
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <Note>Opens a merge request in a repository you contribute to. Its checks and independent review decide whether
        it becomes knowledge.</Note>
      <input value={repository} onChange={(e) => setRepository(e.target.value)} placeholder="Repository, e.g. rrsrch/msc-knee-oa"
        style={inputStyle} />
      <textarea rows={3} value={proposition} onChange={(e) => setProposition(e.target.value)} style={{ ...inputStyle, resize: 'vertical' }}
        placeholder="The claim, stated exactly as the evidence supports it" />
      <select aria-label="claim type" value={type} onChange={(e) => setType(e.target.value)} style={inputStyle}>
        {CLAIM_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
      </select>
      {post.evidence.length === 0 && <Note tone="error">This post cites no passages; a claim needs evidence.</Note>}
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn small kind="primary" disabled={!repository.trim() || !proposition.trim()} onClick={send}>Open merge request</Btn>
        <Btn small onClick={() => setOpen(false)}>Cancel</Btn>
      </div>
      {result?.error && <Note tone="error">{result.error}</Note>}
    </div>
  );
}

function StatusControls({ post, apiKey, onChanged }) {
  const [err, setErr] = useState('');
  if (!apiKey || post.status === 'promoted') return null;
  const set = async (status) => {
    const r = await engine(`/v1/posts/${post.id}`, { key: apiKey, method: 'PATCH', body: { status } });
    if (r.ok) { setErr(''); onChanged(); } else setErr(r.error);
  };
  const options = post.status === 'open'
    ? [...(post.kind === 'question' ? [['answered', 'Mark answered']] : []), ['closed', 'Close']]
    : [['open', 'Reopen']];
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      {options.map(([s, l]) => <Btn key={s} small onClick={() => set(s)} title="The author or a maintainer">{l}</Btn>)}
      {err && <Note tone="error">{err}</Note>}
    </span>
  );
}

export function PostPage({ postId, isMobile }) {
  const apiKey = readStored(KEY_STORAGE);
  const [got, reload] = useLoad(() => engine(`/v1/posts/${postId}`, { key: apiKey }), [postId, apiKey]);
  const [msg, setMsg] = useState('');
  if (got.loading && !got.data) return <Loading what="the post" />;
  if (got.error) return <Note tone="error">{got.error === 'not found' ? `No post ${postId} you can see.` : got.error}</Note>;
  const { post, promoted, reactions, comments, verification } = got.data;
  const target = `post:${postId}`;
  const follow = async () => {
    const r = await engine('/v1/subscriptions', { key: apiKey, method: 'POST', body: { target } });
    setMsg(r.ok ? 'Following this post.' : r.error);
  };
  return (
    <div style={{ fontFamily: fonts.main, display: 'grid', gap: 20 }}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 13 }}>
        <a href="#/explore" style={{ color: '#888' }}>← Explore</a>
      </div>
      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12, fontSize: 13 }}>
          <Mono>post {post.id}</Mono><KindChip kind={post.kind} /><Chip color={STATUS_COLOR[post.status]}>{post.status}</Chip>
          <Mono>{post.repository}</Mono><span style={{ color: '#777' }}>by</span>
          <Author name={post.author} kind={post.author_kind} /><span style={{ color: '#777' }}>{when(post.created_at)}</span>
        </div>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 22 : 30, fontWeight: 700, lineHeight: 1.3,
          letterSpacing: '-0.02em' }}>{post.title}</h1>
        <p style={{ color: '#888', fontSize: 12.5, margin: '8px 0 0' }}>{POSTS_NOTE}</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1.15fr) minmax(0, 1fr)', gap: 20,
        alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 20 }}>
          <Panel title="Post">
            <p style={{ margin: 0, color: '#ddd', fontSize: 14.5, lineHeight: 1.65, whiteSpace: 'pre-wrap' }}>{post.body}</p>
            {post.topics.length > 0 && (
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12, fontSize: 12 }}>
                {post.topics.map((t) => <span key={t} style={{ color: '#9ab' }}>#{t}</span>)}
              </div>
            )}
            {post.evidence.length > 0 && <div style={{ ...sectionLabel, marginTop: 16 }}>Evidence</div>}
            {post.evidence.map((ev) => (
              <blockquote key={`${ev.source_id}-${ev.start}`} style={{ margin: '0 0 8px', borderLeft: `3px solid ${GREEN}`,
                padding: '6px 12px', color: '#ccc', fontSize: 13.5, lineHeight: 1.6 }}>
                “{ev.excerpt ?? 'passage no longer available'}”
                <div style={{ marginTop: 4, fontSize: 11, color: '#777', fontFamily: fonts.mono }}>
                  {short(ev.source_title || '', 80)} ({ev.source_id})</div>
              </blockquote>
            ))}
            {promoted && (
              <Note tone={promoted.state === 'merged' ? 'ok' : 'muted'}>
                Proposed as a claim in {promoted.repository}: merge request {promoted.merge_request_id} is {promoted.state}.{' '}
                {promoted.claim_id
                  ? <a href={`#/claims/${promoted.claim_id}`} style={{ color: GREEN }}>See claim {promoted.claim_id}</a>
                  : <a href={`#/agents?tab=review&repo=${encodeURIComponent(promoted.repository)}`} style={{ color: '#9ab' }}>Review it</a>}
              </Note>
            )}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
              <StatusControls post={post} apiKey={apiKey} onChanged={reload} />
              {apiKey && <Btn small onClick={follow}>Follow</Btn>}
            </div>
            {msg && <Note tone={msg.startsWith('Following') ? 'ok' : 'error'}>{msg}</Note>}
            <div style={{ marginTop: 12 }}><Promote post={post} promoted={promoted} apiKey={apiKey} onChanged={reload} /></div>
          </Panel>
          <Panel title="Reproduction and use" right={<Chip color={GREEN}>evidence</Chip>}>
            <VerificationReports target={target} data={verification} apiKey={apiKey} onChanged={reload} />
          </Panel>
        </div>
        <Panel title="Discussion" right={<Chip>informal</Chip>}>
          <p style={{ margin: '0 0 12px', color: '#888', fontSize: 12.5 }}>Reactions help people find things. Popularity is not evidence.</p>
          <Reactions target={target} data={reactions} apiKey={apiKey} onChanged={reload} />
          <div style={{ marginTop: 14 }}>
            <Thread target={target} messages={comments} apiKey={apiKey} onChanged={reload}
              emptyText={post.kind === 'question' ? 'No answers yet.' : 'No comments yet.'} />
          </div>
        </Panel>
      </div>
    </div>
  );
}
