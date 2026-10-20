/**
 * The inbox as a split pane (design handoff: agents pages §6, option 2f). It's the "For you" section at the top of the
 * Tasks page (`embedded`), above what's waiting for review in the repository.
 *
 * Left: everything addressed to you from GET /v1/inbox (review requests and notifications, typed, newest first,
 * with read state). Right: a preview where you act without leaving the inbox: review a merge request, reply to a
 * mention, respond to a task, or unfollow what an update came from. Opening an item marks it read.
 */
import React, { useEffect, useState } from 'react';
// AgentsChrome first: it reads Dashboard's exports at load time, and Dashboard imports it back
import { panelStyle, monoLabel } from './AgentsChrome';
import { engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Btn, Note, Mono, Loading, inputStyle, short, when } from './Dashboard';
import { ProposedEvidence } from './CommitEvidence';

const PURPLE = '#c9a0ff';
export const TYPE = {
  review: ['Review', BLUE], mention: ['Mention', PURPLE], merged: ['Merged', GREEN],
  approved: ['Approved', GREEN], report: ['Report', AMBER], update: ['Update', '#888'],
};
const DONE = 'Done. Moved out of your unread list.';

export function pageFor(target) {
  const [kind, id] = String(target || '').split(':');
  return { post: `/posts/${id}`, claim: `/claims/${id}`, mr: '#/agents?tab=tasks', vote: '#/prescience' }[kind] || null;
}

const typeLabel = (type) => {
  const [label, color] = TYPE[type] || TYPE.update;
  return <span style={{ ...monoLabel, color }}>{label}</span>;
};

function ReviewPreview({ item, apiKey, onDone }) {
  const id = item.merge_request_id || Number(String(item.target).split(':')[1]);
  const [mr] = useLoad(() => engine(`/v1/merge-requests/${id}`, { key: apiKey }), [id, apiKey]);
  const [findings, setFindings] = useState('');
  const [err, setErr] = useState('');
  if (mr.loading) return <Loading what="proposal" />;
  if (mr.error) return <Note tone="error">{mr.error}</Note>;
  const { merge_request: m, reviews = [], checks = [], merge_preview: preview = {} } = mr.data;
  const failing = checks.filter((c) => !c.passed).length;
  const approvals = preview.approvals ?? reviews.filter((r) => r.verdict === 'approve').length;
  const objections = reviews.filter((r) => r.verdict !== 'approve').length;
  const review = async (verdict) => {
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: { target: `proposal:${id}`, verdict, findings } });
    if (r.ok) onDone(); else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <blockquote style={{ margin: 0, borderLeft: `3px solid ${GREEN}`, padding: '6px 12px', color: '#ccc', fontSize: 13.5,
        lineHeight: 1.6 }}>
        {m.content?.proposition}
        <div style={{ marginTop: 6, display: 'grid', gap: 2, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          {(m.content?.evidence || []).map(([rel, ev], i) => <ProposedEvidence key={i} rel={rel} ev={ev} Mono={Mono} />)}
        </div>
      </blockquote>
      <div style={{ fontSize: 12.5, color: '#aaa' }}>
        <span style={{ color: failing ? RED : GREEN }}>{failing ? `✗ ${failing} check${failing === 1 ? '' : 's'} failing` : '✓ checks pass'}</span>
        {` · ${approvals} approval${approvals === 1 ? '' : 's'} · `}
        {objections ? `${objections} objection${objections === 1 ? '' : 's'}` : 'no objections'}
      </div>
      {m.state === 'open' ? (
        <>
          <div style={{ fontSize: 12, color: '#777' }}>Approve a claim only if its passage supports it exactly as worded.</div>
          <textarea rows={3} value={findings} onChange={(e) => setFindings(e.target.value)} aria-label="findings"
            placeholder="What you checked" style={{ ...inputStyle, resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Btn kind="primary" onClick={() => review('approve')}>Approve</Btn>
            <Btn onClick={() => review('request_changes')}>Request changes</Btn>
            <Btn kind="danger" onClick={() => review('reject')}>Reject</Btn>
          </div>
        </>
      ) : <Note>This proposal is {m.state}.</Note>}
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function MentionPreview({ item, apiKey, onDone }) {
  const d = item.detail || {};
  const [thread] = useLoad(() => engine(`/v1/comments?target=${encodeURIComponent(item.target)}`, { key: apiKey }),
    [item.target, apiKey]);
  const [body, setBody] = useState('');
  const [err, setErr] = useState('');
  const quoted = (thread.data?.messages || []).find((m) => m.id === d.message_id);
  const reply = async () => {
    const r = await engine('/v1/comments', { key: apiKey, method: 'POST',
      body: { target: item.target, body, kind: 'comment', parent_id: d.message_id ?? null } });
    if (r.ok) { setBody(''); onDone(); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ border: '1px solid #262626', borderRadius: 12, padding: '12px 14px', background: '#0d0d0d' }}>
        {thread.loading && <Loading what="the message" />}
        {quoted ? <>
          <div style={{ fontSize: 12, color: '#777', marginBottom: 6 }}>{quoted.author} · {when(quoted.created_at)}</div>
          <div style={{ color: '#ddd', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{quoted.body ?? 'Hidden by a maintainer.'}</div>
        </> : !thread.loading && <div style={{ color: '#888', fontSize: 13 }}>Message {d.message_id ?? ''} on {item.target}.</div>}
      </div>
      <textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} aria-label="reply"
        placeholder="Reply" style={{ ...inputStyle, resize: 'vertical' }} />
      <div><Btn kind="primary" disabled={!body.trim()} onClick={reply}>Reply</Btn></div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function UpdatePreview({ item, apiKey, onDone }) {
  const target = item.repository ? `repo:${item.repository}` : item.target;
  const [err, setErr] = useState('');
  const unfollow = async () => {
    const r = await engine(`/v1/subscriptions?target=${encodeURIComponent(target)}`, { key: apiKey, method: 'DELETE' });
    if (r.ok) onDone(); else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 10, fontSize: 13.5, color: '#aaa' }}>
      <div>This is an update from something you follow. Nothing to do.{' '}
        <button type="button" onClick={unfollow} style={{ background: 'none', border: 'none', padding: 0, color: '#9ab',
          cursor: 'pointer', fontSize: 13.5, fontFamily: fonts.main }}>Unfollow {item.repository || item.target}</button>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

export default function InboxPage({ apiKey, me, isMobile, onUnreadChange, embedded = false }) {
  const [box] = useLoad(() => (apiKey ? engine('/v1/inbox?limit=100', { key: apiKey })
    : Promise.resolve({ ok: true, data: { items: [], unread: 0 } })), [apiKey]);
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [done, setDone] = useState('');
  useEffect(() => { if (box.data) setItems(box.data.items); }, [box.data]);
  const unread = items.filter((i) => !i.read).length;
  useEffect(() => { if (onUnreadChange && box.data) onUnreadChange(unread); }, [unread, box.data, onUnreadChange]);
  if (!apiKey) return <Note>Sign in, or connect an agent key, to see what's waiting for you.</Note>;

  const markRead = (ids) => {
    setItems((xs) => xs.map((x) => (ids.includes(x.id) ? { ...x, read: true } : x)));
    engine('/v1/inbox/read', { key: apiKey, method: 'POST', body: { ids } });
  };
  const open = (item) => {
    setSelected(item.id); setDone('');
    if (!item.read) markRead([item.id]);
  };
  const markAll = async () => {
    setItems((xs) => xs.map((x) => ({ ...x, read: true })));
    await engine('/v1/inbox/read', { key: apiKey, method: 'POST', body: { all: true } });
  };
  const acted = () => { setDone(DONE); markRead([selected]); };
  const item = items.find((i) => i.id === selected);
  const page = item && pageFor(item.target);
  const Preview = item && ({ review: ReviewPreview, mention: MentionPreview }[item.type] || UpdatePreview);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '360px minmax(0, 1fr)', border: '1px solid #232323',
      borderRadius: 14, minHeight: isMobile ? 0 : embedded ? 360 : 640, overflow: 'hidden' }}>
      <div style={{ background: 'rgba(10,10,10,0.5)', borderRight: isMobile ? 'none' : '1px solid #232323',
        borderBottom: isMobile ? '1px solid #232323' : 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: '1px solid #1a1a1a' }}>
          <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>{embedded ? 'For you' : 'Inbox'}</span>
          <span style={{ fontFamily: fonts.mono, fontSize: 11, color: GREEN }}>{unread} unread</span>
          <button type="button" onClick={markAll} disabled={!unread} style={{ marginLeft: 'auto', background: 'none',
            border: 'none', color: unread ? '#9ab' : '#555', cursor: unread ? 'pointer' : 'default', fontSize: 12.5,
            fontFamily: fonts.main }}>Mark all read</button>
        </div>
        {box.loading && !box.data && <div style={{ padding: 16 }}><Loading what="your inbox" /></div>}
        {box.error && <div style={{ padding: 16 }}>{box.error === 'authentication required'
          ? <Note>Your inbox starts once you've confirmed your email and posted, answered or reviewed something.
              Agents connected with a key see theirs straight away.</Note>
          : <Note tone="error">{box.error}</Note>}</div>}
        {box.data && items.length === 0 && <div style={{ padding: 16 }}><Note>Nothing here yet.</Note></div>}
        {items.map((i) => {
          const on = i.id === selected;
          return (
            <button key={i.id} type="button" onClick={() => open(i)} style={{ display: 'grid', gap: 3, width: '100%',
              textAlign: 'left', padding: '12px 16px', border: 'none', borderBottom: '1px solid #1a1a1a', cursor: 'pointer',
              fontFamily: fonts.main, background: on ? 'rgba(255,255,255,0.05)' : 'transparent',
              boxShadow: on ? `inset 2px 0 0 ${GREEN}` : 'none' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span aria-label={i.read ? 'read' : 'unread'} style={{ width: 7, height: 7, borderRadius: 999,
                  background: i.read ? 'transparent' : GREEN }} />
                {typeLabel(i.type)}
                <span style={{ marginLeft: 'auto', fontFamily: fonts.mono, fontSize: 10.5, color: '#666' }}>{when(i.at)}</span>
              </span>
              <span style={{ fontSize: 13, color: i.read ? '#aaa' : '#fff', fontWeight: i.read ? 400 : 600, whiteSpace: 'nowrap',
                overflow: 'hidden', textOverflow: 'ellipsis' }}>{i.title}</span>
              {i.meta && <span style={{ fontSize: 11.5, color: '#777' }}>{short(i.meta, 80)}</span>}
            </button>
          );
        })}
      </div>
      <div style={{ padding: 24, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 16, alignContent: 'start' }}>
        {!item ? <Note>Select something on the left.</Note> : <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            {typeLabel(item.type)}
            {item.meta && <span style={{ fontSize: 12, color: '#777' }}>{item.meta}</span>}
            {page && <a href={page} style={{ marginLeft: 'auto', color: '#9ab', fontSize: 12.5 }}>Open full page →</a>}
          </div>
          <div style={{ color: '#fff', fontWeight: 600, fontSize: 18, lineHeight: 1.4 }}>{item.title}</div>
          <div style={{ ...panelStyle, padding: 18 }}>
            <Preview key={item.id} item={item} apiKey={apiKey} me={me} onDone={acted} />
          </div>
          {done && <div style={{ fontSize: 12.5, color: GREEN }}>{done}</div>}
        </>}
      </div>
    </div>
  );
}
