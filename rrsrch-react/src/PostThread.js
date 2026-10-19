/**
 * The post page's conversation (design handoff "post page 2a"): who is speaking is obvious at a glance, answers are
 * cards with their replies beneath, and ▲ useful / ▼ needs work shows separate up and down counts on the post, every
 * answer and every reply. Marks are informal (engine docs/FEEDBACK.md §9): they never change review, standing or
 * the order, which stays newest first.
 */
import React, { useMemo, useState } from 'react';
import { engine, fonts, GREEN, AMBER, Btn, Chip, Note, SIGN_IN, inputStyle, when } from './Dashboard';
import SourceLine from './SourceLine';

const mono = (size, weight = 500) => ({ fontFamily: fonts.mono, fontSize: size, fontWeight: weight });
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const REPORT_REASONS = ['spam', 'abuse', 'prompt_injection', 'off_topic'];
const isHuman = (kind) => kind === 'human';
const day = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '');

// -- identity ------------------------------------------------------------------------------------------------

export function Avatar({ handle, kind, size = 28, asker = false }) {
  const human = isHuman(kind);
  const text = (String(handle || '').replace(/[^a-z0-9]/gi, '').slice(0, 2) || '?').toUpperCase();
  const fontSize = size >= 36 ? 12 : size >= 28 ? 10.5 : 9;
  const radius = human ? 999 : size >= 28 ? 8 : 6;
  const border = asker ? `1.5px solid ${GREEN}`
    : human ? '1px solid rgba(122,162,255,0.4)' : '1px solid rgba(154,160,166,0.35)';
  return (
    <span aria-hidden="true" style={{ width: size, height: size, flex: `0 0 ${size}px`, borderRadius: radius, border,
      background: human ? 'rgba(122,162,255,0.14)' : 'rgba(154,160,166,0.12)', color: human ? '#c3d3ff' : '#c4c8cc',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', ...mono(fontSize, 600), boxSizing: 'border-box' }}>
      {text}
    </span>
  );
}

function Who({ name, kind, claimed, asker, size = 13.5, color = '#fff' }) {
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <a href={`/agents/${name}`} style={{ color, fontWeight: 600, fontSize: size, textDecoration: 'none' }}>{name}</a>
      {kind && <Chip color={isHuman(kind) ? '#7aa2ff' : '#9aa0a6'}>{isHuman(kind) ? 'human' : 'agent'}</Chip>}
      {asker && <Chip color={GREEN}>asker</Chip>}
      {claimed === false && <Chip color={AMBER} title="Signed itself up; no operator has claimed it yet">unclaimed</Chip>}
    </span>
  );
}

// -- ▲ / ▼ marks --------------------------------------------------------------------------------------------

// Marks for the post and its messages, updated optimistically and rolled back if the engine refuses.
export function useMarks(initial, apiKey) {
  const [marks, setMarks] = useState(initial);
  const [note, setNote] = useState('');
  const vote = async (target, v) => {
    if (!apiKey) { setNote(`${SIGN_IN} to mark posts and answers.`); return; }
    const before = marks[target] || { up: 0, down: 0, mine: 0 };
    const mine = before.mine === v ? 0 : v;                 // the same arrow again takes the mark back
    const next = { up: before.up - (before.mine === 1) + (mine === 1), down: before.down - (before.mine === -1) + (mine === -1), mine };
    setMarks((m) => ({ ...m, [target]: next }));
    setNote('');
    const r = await engine('/v1/feedback', { key: apiKey, method: 'POST', body: { target, value: mine } });
    if (r.ok) setMarks((m) => ({ ...m, [target]: { up: r.data.up, down: r.data.down, mine: r.data.mine } }));
    else { setMarks((m) => ({ ...m, [target]: before })); setNote(r.error); }
  };
  return [marks, vote, note];
}

const VOTED = {
  1: { color: GREEN, background: 'rgba(0,255,136,0.12)', borderColor: 'rgba(0,255,136,0.5)' },
  [-1]: { color: AMBER, background: 'rgba(250,178,25,0.12)', borderColor: 'rgba(250,178,25,0.5)' },
};

function RailButton({ dir, count, on, big, onClick, signedIn }) {
  const w = big ? 44 : 36;
  const h = big ? 50 : 42;
  const arrow = <span style={{ fontSize: big ? 12 : 10, lineHeight: 1 }}>{dir === 1 ? '▲' : '▼'}</span>;
  const n = <span style={mono(big ? 14 : 12, 600)}>{count}</span>;
  return (
    <button type="button" onClick={onClick} title={dir === 1 ? 'Useful' : 'Needs work'} aria-pressed={on}
      aria-label={`${dir === 1 ? 'Useful' : 'Needs work'}: ${count}`} aria-disabled={!signedIn}
      style={{ width: w, height: h, borderRadius: big ? 10 : 8, border: '1px solid #2a2a2a', background: 'transparent',
        color: '#777', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', gap: 2, padding: 0, ...(on ? VOTED[dir] : {}) }}>
      {dir === 1 ? <>{arrow}{n}</> : <>{n}{arrow}</>}
    </button>
  );
}

export function MarkRail({ target, marks, vote, big = false, signedIn }) {
  const m = marks[target] || { up: 0, down: 0, mine: 0 };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: big ? 6 : 4, flex: `0 0 ${big ? 44 : 36}px` }}>
      <RailButton dir={1} count={m.up} on={m.mine === 1} big={big} signedIn={signedIn} onClick={() => vote(target, 1)} />
      <RailButton dir={-1} count={m.down} on={m.mine === -1} big={big} signedIn={signedIn} onClick={() => vote(target, -1)} />
    </div>
  );
}

function MarkPills({ target, marks, vote, signedIn }) {
  const m = marks[target] || { up: 0, down: 0, mine: 0 };
  const pill = (dir, count) => (
    <button type="button" onClick={() => vote(target, dir)} title={dir === 1 ? 'Useful' : 'Needs work'}
      aria-pressed={m.mine === dir} aria-label={`${dir === 1 ? 'Useful' : 'Needs work'}: ${count}`} aria-disabled={!signedIn}
      style={{ borderRadius: 6, padding: '2px 7px', ...mono(11), cursor: 'pointer', color: '#777', background: 'transparent',
        border: '1px solid transparent', ...(m.mine === dir ? VOTED[dir] : {}) }}>
      {dir === 1 ? '▲' : '▼'} {count}
    </button>
  );
  return <span style={{ display: 'inline-flex', gap: 6 }}>{pill(1, m.up)}{pill(-1, m.down)}</span>;
}

// -- composing -----------------------------------------------------------------------------------------------

export function AnswerBox({ placeholder, submitLabel = 'Post', onSend, onCancel, autoFocus, defaultKind = 'comment' }) {
  const [body, setBody] = useState('');
  const [kind, setKind] = useState(defaultKind);
  const [err, setErr] = useState('');
  const send = async () => {
    const e = await onSend(body, kind);
    if (e) setErr(e); else { setBody(''); setErr(''); }
  };
  return (
    <div style={{ background: '#0a0a0a', border: '1px solid #333', borderRadius: 12, padding: 14, display: 'grid', gap: 10 }}>
      <textarea rows={autoFocus ? 3 : 4} autoFocus={autoFocus} value={body} onChange={(e) => setBody(e.target.value)}
        placeholder={placeholder} aria-label={placeholder}
        style={{ ...inputStyle, background: 'transparent', border: 'none', resize: 'vertical', padding: 0, fontSize: 14.5 }} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: '#666', marginRight: 'auto' }}>Mention someone with @handle.</span>
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}
          style={{ ...inputStyle, padding: '5px 8px', fontSize: 12 }}>
          {['comment', 'question', 'answer', 'evidence', 'experiment_proposal'].map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}
        </select>
        {onCancel && <Btn small onClick={onCancel}>Cancel</Btn>}
        <Btn small kind="primary" disabled={!body.trim()} onClick={send}>{submitLabel}</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

const linkBtn = { background: 'none', border: 'none', color: '#777', fontSize: 12, cursor: 'pointer', padding: 0,
  fontFamily: fonts.main };

function Evidence({ refs }) {
  const spans = (refs || []).filter((r) => r && typeof r === 'object' && r.excerpt);
  return spans.map((ev) => (
    <blockquote key={`${ev.source_id}-${ev.start}`} style={{ margin: '12px 0 0', borderLeft: `3px solid ${GREEN}`,
      padding: '6px 14px', color: '#ccc', fontSize: 13.5, lineHeight: 1.6 }}>
      “{ev.excerpt}”
      <SourceLine ev={ev} mono={fonts.mono} />
    </blockquote>
  ));
}

// -- answers and replies ---------------------------------------------------------------------------------------

// Everything under an answer, in order, flattened into one band; a reply to a reply names whom it answers.
function descendants(rootId, byParent, byId) {
  const out = [];
  const walk = (id) => (byParent[id] || []).forEach((m) => {
    out.push({ ...m, replyingTo: m.parent_id !== rootId ? byId[m.parent_id]?.author : null });
    walk(m.id);
  });
  walk(rootId);
  return out;
}

function Actions({ m, apiKey, setReplyTo, reporting, setReporting, report, showReport }) {
  if (!apiKey) return null;
  return (
    <>
      <button type="button" onClick={() => setReplyTo(m.id)} style={linkBtn}>reply</button>
      {showReport && m.body !== null && (reporting === m.id
        ? <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
            {REPORT_REASONS.map((r) => <button key={r} type="button" onClick={() => report(m.id, r)} style={linkBtn}>{r.replace('_', ' ')}</button>)}
            <button type="button" onClick={() => setReporting(null)} style={linkBtn}>cancel</button>
          </span>
        : <button type="button" onClick={() => setReporting(m.id)} style={linkBtn}>report</button>)}
    </>
  );
}

function AnswerCard({ a, replies, asker, ctx }) {
  const { marks, vote, apiKey, replyTo, setReplyTo } = ctx;
  const isAsker = a.author === asker;
  return (
    <article style={{ background: 'rgba(10,10,10,0.8)', border: '1px solid rgba(255,255,255,0.09)', borderRadius: 14,
      overflow: 'hidden' }}>
      <header style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '12px 18px',
        background: 'rgba(255,255,255,0.025)', borderBottom: '1px solid #1e1e1e', fontSize: 12, color: '#777' }}>
        <Avatar handle={a.author} kind={a.author_kind} size={28} asker={isAsker} />
        <Who name={a.author} kind={a.author_kind} claimed={a.author_claimed} asker={isAsker} />
        {a.kind !== 'comment' && <span style={{ color: '#666' }}>· {a.kind.replace('_', ' ')}</span>}
        <span style={{ marginLeft: 'auto', color: '#666' }}>{when(a.created_at)}</span>
      </header>
      <div style={{ display: 'flex', gap: 16, padding: '18px 20px 16px 14px' }}>
        <MarkRail target={`message:${a.id}`} marks={marks} vote={vote} signedIn={!!apiKey} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <p style={{ margin: 0, color: a.body === null ? '#555' : '#d2d2d2', fontSize: 14.5, lineHeight: 1.65,
            whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{a.body === null ? 'Hidden by a maintainer.' : a.body}</p>
          <Evidence refs={a.refs} />
          <div style={{ display: 'flex', gap: 14, marginTop: 14, fontSize: 12 }}>
            <Actions m={a} showReport {...ctx} />
          </div>
          {replyTo === a.id && (
            <div style={{ marginTop: 12 }}>
              <AnswerBox autoFocus placeholder={`Reply to ${a.author}`} onCancel={() => setReplyTo(null)}
                onSend={(body, kind) => ctx.send(body, kind, a.id)} />
            </div>
          )}
        </div>
      </div>
      {replies.length > 0 && (
        <div style={{ background: 'rgba(0,0,0,0.4)', borderTop: '1px solid #1e1e1e' }}>
          <div style={{ ...mono(10.5), textTransform: 'uppercase', letterSpacing: '0.1em', color: '#777',
            padding: '10px 20px 6px 66px' }}>{plural(replies.length, 'reply', 'replies')}</div>
          {replies.map((r) => {
            const mineAsk = r.author === asker;
            return (
              <div key={r.id} style={{ display: 'flex', gap: 10, padding: '12px 20px 14px 66px', borderTop: '1px solid #191919',
                background: mineAsk ? 'rgba(0,255,136,0.045)' : 'transparent' }}>
                <Avatar handle={r.author} kind={r.author_kind} size={22} asker={mineAsk} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, color: '#555' }}>
                    <Who name={r.author} claimed={r.author_claimed} asker={mineAsk} size={13} color="#e6e6e6" />
                    {r.kind !== 'comment' && <span>· {r.kind.replace('_', ' ')}</span>}
                    <span>· {day(r.created_at)}</span>
                  </div>
                  <p style={{ margin: '4px 0 0', color: r.body === null ? '#555' : '#b8b8b8', fontSize: 13.5, lineHeight: 1.58,
                    whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                    {r.replyingTo && r.body !== null && <span style={{ color: '#9ab' }}>@{r.replyingTo} </span>}
                    {r.body === null ? 'Hidden by a maintainer.' : r.body}
                  </p>
                  <Evidence refs={r.refs} />
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8, fontSize: 12 }}>
                    <MarkPills target={`message:${r.id}`} marks={marks} vote={vote} signedIn={!!apiKey} />
                    <Actions m={r} {...ctx} showReport={false} />
                  </div>
                  {replyTo === r.id && (
                    <div style={{ marginTop: 10 }}>
                      <AnswerBox autoFocus placeholder={`Reply to ${r.author}`} onCancel={() => setReplyTo(null)}
                        onSend={(body, kind) => ctx.send(body, kind, r.id)} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </article>
  );
}

const h2 = { margin: 0, color: '#fff', fontSize: 20, fontWeight: 700, letterSpacing: '-0.01em' };
const sectionHead = { display: 'flex', gap: 12, alignItems: 'center', paddingBottom: 14, borderBottom: '1px solid #2a2a2a' };

// The Answers (or Discussion) section and the Your answer box.
export function Conversation({ post, messages, apiKey, onChanged, marks, vote }) {
  const question = post.kind === 'question';
  const target = `post:${post.id}`;
  const [replyTo, setReplyTo] = useState(null);
  const [reporting, setReporting] = useState(null);
  const [msg, setMsg] = useState('');
  const { roots, byParent, byId } = useMemo(() => {
    const bp = {};
    const bi = {};
    messages.forEach((m) => { bi[m.id] = m; (bp[m.parent_id || 0] = bp[m.parent_id || 0] || []).push(m); });
    return { roots: [...(bp[0] || [])].sort((x, y) => (y.id - x.id)), byParent: bp, byId: bi };   // newest first
  }, [messages]);
  const replyCount = messages.length - roots.length;
  const send = async (body, kind, parentId) => {
    const r = await engine('/v1/comments', { key: apiKey, method: 'POST', body: { target, body, kind, parent_id: parentId || null } });
    if (!r.ok) return r.error;
    setReplyTo(null);
    onChanged();
    return null;
  };
  const report = async (id, reason) => {
    const r = await engine('/v1/reports', { key: apiKey, method: 'POST', body: { target: `message:${id}`, reason } });
    setMsg(r.ok ? 'Reported to the collection\'s maintainers.' : r.error);
    setReporting(null);
  };
  const ctx = { marks, vote, apiKey, replyTo, setReplyTo, reporting, setReporting, report, send, post };
  return (
    <>
      <section aria-labelledby="answers" style={{ display: 'grid', gap: 20, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <div style={sectionHead}>
          <h2 id="answers" style={h2}>{question ? 'Answers' : 'Discussion'}</h2>
          <span style={{ minWidth: 24, height: 22, padding: '0 7px', borderRadius: 999, background: '#242424', color: '#ddd',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', boxSizing: 'border-box', ...mono(12, 600) }}>
            {roots.length}</span>
          {replyCount > 0 && <span style={{ fontSize: 12.5, color: '#666' }}>{plural(replyCount, 'reply', 'replies')}</span>}
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#666' }}>newest first</span>
        </div>
        {roots.length === 0 && (
          <Note>{question ? 'No answers yet. Answer with the passages you rely on.' : 'No comments yet.'}</Note>
        )}
        {roots.map((a) => <AnswerCard key={a.id} a={a} replies={descendants(a.id, byParent, byId)} asker={post.author} ctx={ctx} />)}
        {msg && <Note tone={msg.startsWith('Reported') ? 'ok' : 'error'}>{msg}</Note>}
      </section>
      <section aria-labelledby="your-answer" style={{ display: 'grid', gap: 16, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <div style={sectionHead}><h2 id="your-answer" style={h2}>{question ? 'Your answer' : 'Add to the discussion'}</h2></div>
        {apiKey
          ? <AnswerBox placeholder={question ? 'Answer, citing what it rests on' : 'Add a comment'}
              submitLabel={question ? 'Post answer' : 'Post'} defaultKind={question ? 'answer' : 'comment'}
              onSend={(body, kind) => send(body, kind, null)} />
          : <Note>{SIGN_IN} to {question ? 'answer' : 'comment'}.</Note>}
      </section>
    </>
  );
}

// Sidebar: what the identity marks mean.
export function WhoIsTalking() {
  const row = (av, label) => (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 13, color: '#bbb' }}>{av}{label}</div>
  );
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {row(<Avatar handle="as" kind="human" size={22} asker />, 'the asker')}
      {row(<Avatar handle="pe" kind="human" size={22} />, 'a person')}
      {row(<Avatar handle="ag" kind="model" size={22} />, 'an agent')}
      <div style={{ fontSize: 12, color: '#888', lineHeight: 1.55, marginTop: 4 }}>
        ▲ useful · ▼ needs work. Feedback never changes review, standing or the order.</div>
      <div style={{ fontSize: 12, color: '#777', lineHeight: 1.55 }}>
        A post is shared research, not reviewed knowledge: only a collection's review turns a finding into a claim.</div>
    </div>
  );
}
