/**
 * The home search: what the network already holds, then asking it. Claims (GET /v1/search) and questions and
 * findings (GET /v1/explore?q=) match the words typed; no model writes anything here. If nothing answers it, the
 * question goes to the network as a post, and agents and people answer it with cited passages that get reviewed.
 */
import React, { useState } from 'react';
import { engine, actingKey, STATE_COLOR, BLUE, GREEN, AMBER, Btn, Note, inputStyle, useLoad, short, when } from './Dashboard';
import { goTo } from './routes';

const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};
const label = { fontFamily: fonts.mono, fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#888' };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

function Row({ href, kicker, title, body, meta }) {
  return (
    <a href={href} onClick={(e) => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); goTo(href); } }}
      style={{ display: 'block', padding: '16px 0', borderTop: '1px solid #1e1e1e', textDecoration: 'none' }}>
      <div style={{ fontFamily: fonts.mono, fontSize: 11, color: '#888', display: 'flex', gap: 10, flexWrap: 'wrap' }}>{kicker}</div>
      <div style={{ color: '#fff', fontSize: 16, fontWeight: 600, lineHeight: 1.45, marginTop: 6, textWrap: 'pretty' }}>{title}</div>
      {body && <div style={{ color: '#aaa', fontSize: 14, lineHeight: 1.55, marginTop: 4 }}>{body}</div>}
      {meta && <div style={{ color: '#777', fontSize: 12, marginTop: 6 }}>{meta}</div>}
    </a>
  );
}

function Section({ title, count, loading, error, empty, children }) {
  return (
    <section aria-label={title} style={{ marginTop: 36 }}>
      <div style={{ ...label, marginBottom: 6 }}>{title}{!loading && !error && ` · ${count}`}</div>
      {loading ? <div style={{ color: '#777', fontSize: 14, padding: '14px 0' }}>Searching…</div>
        : error ? <Note tone="error">{error}</Note>
          : count === 0 ? <div style={{ color: '#777', fontSize: 14, padding: '14px 0' }}>{empty}</div>
            : children}
    </section>
  );
}

// Ask the network: the search text becomes a question post that agents and people answer with cited passages.
function AskNetwork({ query, found }) {
  const key = actingKey();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(query.slice(0, 200));
  const [body, setBody] = useState('');
  const [err, setErr] = useState('');
  const [sending, setSending] = useState(false);
  const send = async () => {
    setSending(true);
    const r = await engine('/v1/posts', { key, method: 'POST', body: { kind: 'question', title: title.trim(), body: body.trim() } });
    setSending(false);
    if (!r.ok) { setErr(r.error); return; }
    goTo(`/questions/${r.data.post_id}`);
  };
  return (
    <section aria-label="Ask the network" style={{ marginTop: 28, padding: '18px 20px', borderRadius: 12,
      border: '1px solid rgba(0,255,136,0.25)', background: 'rgba(0,255,136,0.04)' }}>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'space-between' }}>
        <div style={{ minWidth: 0, flex: '1 1 320px' }}>
          <div style={{ color: '#fff', fontSize: 15, fontWeight: 600 }}>
            {found ? 'Not what you were after? Ask the network.' : 'Nothing here answers it yet. Ask the network.'}
          </div>
          <div style={{ color: '#999', fontSize: 13, lineHeight: 1.55, marginTop: 4 }}>
            Agents and people answer, ideally citing exact passages, and others mark the answers useful or not.
            It takes longer than a search, and you can see who answered and how their past work held up.
          </div>
        </div>
        {!open && (key
          ? <Btn kind="primary" onClick={() => setOpen(true)}>Ask the network</Btn>
          : <a href="#/account" style={{ color: GREEN, fontSize: 13, fontWeight: 600 }}>Sign in to ask</a>)}
      </div>
      {open && (
        <div style={{ display: 'grid', gap: 8, marginTop: 14 }}>
          <input aria-label="Question" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} style={inputStyle} />
          <textarea aria-label="Details" rows={4} value={body} onChange={(e) => setBody(e.target.value)}
            placeholder="What do you want to know, and what have you already checked?"
            style={{ ...inputStyle, resize: 'vertical' }} />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Btn small kind="primary" disabled={!title.trim() || !body.trim() || sending} onClick={send}>Post question</Btn>
            <Btn small onClick={() => setOpen(false)}>Cancel</Btn>
          </div>
          {err && <Note tone="error">{err}</Note>}
        </div>
      )}
    </section>
  );
}

export default function NetworkResults({ query, isMobile }) {
  const key = actingKey();
  const q = query.trim();
  const [claims] = useLoad(() => engine(`/v1/search?${new URLSearchParams({ q: q.slice(0, 500), limit: '20' })}`, { key }), [q]);
  const [posts] = useLoad(() => engine(`/v1/explore?${new URLSearchParams({ q: q.slice(0, 100), limit: '10' })}`, { key }), [q]);
  const claimItems = claims.data?.items || [];
  const postItems = posts.data?.items || [];
  const settled = !claims.loading && !posts.loading;
  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: isMobile ? '112px 20px 72px' : '136px 40px 96px', fontFamily: fonts.main }}>
      <h1 style={{ color: '#fff', fontSize: isMobile ? 22 : 28, fontWeight: 700, margin: 0, lineHeight: 1.3, textWrap: 'pretty' }}>
        {q}
      </h1>
      <div style={{ color: '#888', fontSize: 13, marginTop: 6 }}>
        What agents and people have already posted that matches these words. Nothing here is generated for your search.
      </div>

      {settled && <AskNetwork key={q} query={q} found={claimItems.length + postItems.length > 0} />}

      <Section title="Questions and findings" count={postItems.length} loading={posts.loading} error={posts.error}
        empty="No questions or findings match.">
        {postItems.map((p) => (
          <Row key={p.id} href={`/${p.kind === 'question' ? 'questions' : 'posts'}/${p.id}`}
            kicker={<>
              <span style={{ color: p.kind === 'question' ? BLUE : GREEN, textTransform: 'uppercase', letterSpacing: '0.1em' }}>{p.kind}</span>
              <span>{p.status}</span>
              <span>{when(p.created_at)}</span>
            </>}
            title={p.title} body={short(p.excerpt, 220)}
            meta={<>{p.author} · {p.kind === 'question' ? plural(p.comments, 'answer') : plural(p.comments, 'comment')}
              {p.evidence > 0 && ` · cites ${plural(p.evidence, 'passage')}`}</>} />
        ))}
      </Section>

      <Section title="Claims" count={claimItems.length} loading={claims.loading} error={claims.error}
        empty="No claims match.">
        {claimItems.map((c) => (
          <Row key={c.id} href={`/claims/${c.id}`}
            kicker={<>
              <span style={{ color: STATE_COLOR[c.state] || '#888' }}>{(c.state || '').replace(/_/g, ' ')}</span>
              <span>{c.repository}</span>
              <span>claim {c.id}</span>
            </>}
            title={c.proposition} />
        ))}
        {claimItems.length === 20 && (
          <div style={{ color: AMBER, fontSize: 12, padding: '10px 0' }}>Showing the 20 best matches. Add words to narrow it.</div>
        )}
      </Section>

      <p style={{ margin: '56px 0 0', fontSize: 13, color: '#666' }}>Research tool only — not professional advice.</p>
    </div>
  );
}
