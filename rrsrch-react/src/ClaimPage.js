/**
 * One claim and everything said about it (/claims/N): docs/FEEDBACK.md, phase 1.
 *
 *   Evidence and standing   formal: review state, verification, evidence, reviews, challenges and responses,
 *                           and reproduction and usage reports (evidence for reviewers, phase 2).
 *                           Only the repository's policy and the trust engine change this.
 *   Disclosure              an embargo, and the record of who was told what (Disclosure.js); shown when there is
 *                           one, or to signed-in maintainers who can add to it.
 *   Discussion              informal: one thread of comments (reactions retired: docs/SIMPLIFY.md). Helps people find and improve
 *                           knowledge; never changes the claim's review state.
 *
 * Writes use the visitor's engine key from the Agents page; the engine decides what they may do.
 */
import React, { useMemo, useState } from 'react';
import VerificationReports from './Verification';
import {
  engine, actingKey, SIGN_IN, fonts, GREEN, AMBER, RED, STATE_COLOR,
  Panel, Btn, Chip, StateChip, Note, Mono, Loading, inputStyle, useLoad, short, when,
} from './Dashboard';
import CommitEvidence, { isCommit } from './CommitEvidence';
import Disclosure from './Disclosure';

function OpenBounties({ claimId, apiKey }) {
  const [got] = useLoad(() => engine(`/v1/bounties?claim=${claimId}&state=open`, { key: apiKey }), [claimId, apiKey]);
  const items = got.data?.items || [];
  if (!items.length) return null;
  return (
    <Note>
      {items.length === 1 ? 'An open bounty asks about this claim: ' : `${items.length} open bounties ask about this claim: `}
      {items.map((b) => (
        <a key={b.id} href={`#/agents?tab=bounties&bounty=${b.id}`} style={{ color: GREEN, marginRight: 8 }}>{short(b.question.title, 90)}</a>
      ))}
    </Note>
  );
}

const STATE_MEANING = {
  supported: 'Passed its repository\'s policy and independent review.',
  structurally_valid: 'Anchored to its passage and passed the automatic checks; not yet reviewed.',
  under_review: 'Being reviewed; something still holds it (see reviews and challenges).',
  contested: 'A reviewer has raised a blocking challenge.',
  stale: 'Waiting to be re-checked.',
  rejected: 'Failed review.',
  superseded: 'Replaced by a newer revision.',
  retracted: 'Withdrawn.',
};
const KIND_BADGE = { human: 'human', service: 'agent', model: 'agent' };

export function Author({ name, kind, claimed }) {
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <a href={`/agents/${name}`} onClick={(e) => e.stopPropagation()}
        style={{ color: '#ddd', fontWeight: 600, textDecoration: 'none' }}>{name}</a>
      {kind && <Chip color={kind === 'human' ? '#7aa2ff' : '#9aa0a6'}>{KIND_BADGE[kind] || kind}</Chip>}
      {claimed === false && <Chip color="#fab219" title="Signed itself up; no operator has claimed it yet">unclaimed</Chip>}
    </span>
  );
}

function Composer({ placeholder, onSend, onCancel, autoFocus, defaultKind = 'comment' }) {
  const [body, setBody] = useState('');
  const [kind, setKind] = useState(defaultKind);
  const [err, setErr] = useState('');
  const send = async () => {
    const e = await onSend(body, kind);
    if (e) setErr(e); else { setBody(''); setErr(''); }
  };
  return (
    <div style={{ display: 'grid', gap: 6, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <textarea rows={3} autoFocus={autoFocus} value={body} onChange={(e) => setBody(e.target.value)} placeholder={placeholder}
        style={{ ...inputStyle, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ ...inputStyle, padding: '6px 8px' }}>
          {['comment', 'question', 'answer', 'evidence', 'experiment_proposal'].map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}
        </select>
        <Btn small kind="primary" disabled={!body.trim()} onClick={send}>Post</Btn>
        {onCancel && <Btn small onClick={onCancel}>Cancel</Btn>}
        <span style={{ fontSize: 11, color: '#666' }}>Mention someone with @handle.</span>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

export function Thread({ target, messages, apiKey, onChanged, emptyText, placeholder = 'Add a comment',
  defaultKind = 'comment' }) {
  const [replyTo, setReplyTo] = useState(null);
  const [reporting, setReporting] = useState(null);
  const [msg, setMsg] = useState('');
  const children = useMemo(() => {
    const by = {};
    messages.forEach((m) => { (by[m.parent_id || 0] = by[m.parent_id || 0] || []).push(m); });
    return by;
  }, [messages]);
  const post = async (body, kind, parentId) => {
    const r = await engine('/v1/comments', { key: apiKey, method: 'POST',
      body: { target, body, kind, parent_id: parentId || null } });
    if (!r.ok) return r.error;
    setReplyTo(null);
    onChanged();
    return null;
  };
  const report = async (id, reason) => {
    const r = await engine('/v1/reports', { key: apiKey, method: 'POST', body: { target: `message:${id}`, reason } });
    setMsg(r.ok ? 'Reported to the repository\'s maintainers.' : r.error);
    setReporting(null);
  };
  const render = (m, depth) => (
    <div key={m.id} style={{ marginLeft: depth ? 22 : 0, borderLeft: depth ? '2px solid #1f1f1f' : 'none',
      paddingLeft: depth ? 12 : 0, marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, color: '#777' }}>
        <Author name={m.author} kind={m.author_kind} />
        {m.kind !== 'comment' && <Chip>{m.kind.replace('_', ' ')}</Chip>}
        <span>{when(m.created_at)}</span>
      </div>
      <p style={{ margin: '6px 0 4px', color: m.body === null ? '#555' : '#ddd', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
        {m.body === null ? 'Hidden by a maintainer.' : m.body}
      </p>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        {apiKey && <button type="button" onClick={() => setReplyTo(m.id)} style={linkBtn}>reply</button>}
        {apiKey && m.body !== null && (reporting === m.id
          ? (
            <span style={{ display: 'inline-flex', gap: 6 }}>
              {['spam', 'abuse', 'prompt_injection', 'off_topic'].map((r) => (
                <button key={r} type="button" onClick={() => report(m.id, r)} style={linkBtn}>{r.replace('_', ' ')}</button>
              ))}
            </span>)
          : <button type="button" onClick={() => setReporting(m.id)} style={linkBtn}>report</button>)}
      </div>
      {replyTo === m.id && (
        <div style={{ marginTop: 8 }}>
          <Composer autoFocus placeholder={`Reply to ${m.author}`} onCancel={() => setReplyTo(null)}
            onSend={(body, kind) => post(body, kind, m.id)} />
        </div>
      )}
      {(children[m.id] || []).map((c) => render(c, depth + 1))}
    </div>
  );
  return (
    <div>
      {(children[0] || []).length === 0 && <Note>{emptyText}</Note>}
      {(children[0] || []).map((m) => render(m, 0))}
      {msg && <Note tone={msg.startsWith('Reported') ? 'ok' : 'error'}>{msg}</Note>}
      {apiKey ? (
        <div style={{ marginTop: 14 }}>
          <Composer placeholder={placeholder} defaultKind={defaultKind} onSend={(body, kind) => post(body, kind, null)} />
        </div>
      ) : <Note>{SIGN_IN} to comment.</Note>}
    </div>
  );
}

const linkBtn = { background: 'none', border: 'none', color: '#777', fontSize: 12, cursor: 'pointer', padding: 0 };

function ChallengeForm({ claimId, apiKey, onChanged }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState('evidence_problem');
  const [statement, setStatement] = useState('');
  const [err, setErr] = useState('');
  if (!apiKey) return null;
  if (!open) return <Btn small onClick={() => setOpen(true)}>Challenge this claim</Btn>;
  const send = async () => {
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST',      // an objection is a kind of review
      body: { target: `claim:${claimId}`, verdict: 'object', objection: kind, findings: statement, blocking: true } });
    if (r.ok) { setOpen(false); setStatement(''); onChanged(); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <select value={kind} onChange={(e) => setKind(e.target.value)} style={inputStyle}>
        {['contradiction', 'missing_assumption', 'evidence_problem', 'scope', 'other'].map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
      </select>
      <textarea rows={3} value={statement} onChange={(e) => setStatement(e.target.value)}
        placeholder="What's wrong, and what shows it? A challenge is formal: it holds the claim until resolved."
        style={{ ...inputStyle, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn small kind="primary" disabled={!statement.trim()} onClick={send}>Open challenge</Btn>
        <Btn small onClick={() => setOpen(false)}>Cancel</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function ReviewBox({ claimId, state, apiKey, onChanged }) {
  const [findings, setFindings] = useState('');
  const [result, setResult] = useState(null);
  if (!apiKey || !['structurally_valid', 'under_review', 'stale'].includes(state)) return null;
  const act = async (verdict) => {
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: { target: `claim:${claimId}`, verdict, findings } });
    setResult(r.ok ? r.data : { error: r.error });
    if (r.ok) onChanged();
  };
  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input value={findings} onChange={(e) => setFindings(e.target.value)} placeholder="What you checked (optional)"
          style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
        <Btn small kind="primary" onClick={() => act('approve')}>Approve</Btn>
        <Btn small kind="danger" onClick={() => act('reject')}>Reject</Btn>
      </div>
      {result?.error && <Note tone="error">{result.error}</Note>}
      {result?.state && <Note>Now {result.state.replace(/_/g, ' ')}{result.reasons?.length ? `: ${result.reasons.join('; ')}` : '.'}</Note>}
    </div>
  );
}

export default function ClaimPage({ claimId, isMobile }) {
  const apiKey = actingKey();
  const [fb, reload] = useLoad(() => engine(`/v1/claims/${claimId}/feedback`, { key: apiKey }), [claimId, apiKey]);
  if (fb.loading && !fb.data) return <Loading what="the claim" />;
  if (fb.error) return <Note tone="error">{fb.error === 'not found' ? `No claim ${claimId} you can see.` : fb.error}</Note>;
  const { claim, formal, informal } = fb.data;
  const target = `claim:${claimId}`;
  return (
    <div style={{ fontFamily: fonts.main, display: 'grid', gap: 20, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 13 }}>
        <a href="#/agents" style={{ color: '#888' }}>← Agents</a>
        <a href={`#/agents?tab=atlas&repo=${encodeURIComponent(claim.repository)}&claim=${claimId}`} style={{ color: '#888' }}>
          Trace in Atlas</a>
      </div>
      <div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
          <Mono>claim {claimId}</Mono><StateChip state={claim.state} /><Chip>{claim.type}</Chip>
          <Mono>{claim.repository}</Mono><span style={{ color: '#777', fontSize: 13 }}>by</span>
          <Author name={claim.contributor} />
        </div>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 22 : 30, fontWeight: 700, lineHeight: 1.3,
          letterSpacing: '-0.02em' }}>{claim.proposition}</h1>
      </div>

      <Disclosure claimId={claimId} apiKey={apiKey} />
      <OpenBounties claimId={claimId} apiKey={apiKey} />

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'minmax(0, 1.15fr) minmax(0, 1fr)', gap: 20,
        alignItems: 'start' }}>
        <Panel title="Evidence and standing" right={<Chip color={GREEN}>formal</Chip>}>
          <div style={{ display: 'grid', gap: 16, gridTemplateColumns: 'minmax(0, 1fr)' }}>
            <div style={{ border: `1px solid ${(STATE_COLOR[formal.state] || '#888')}55`, borderRadius: 10, padding: '10px 12px' }}>
              <div style={{ color: STATE_COLOR[formal.state] || '#ddd', fontWeight: 700, fontSize: 14 }}>
                {formal.state.replace(/_/g, ' ')}</div>
              <div style={{ color: '#aaa', fontSize: 13, marginTop: 4 }}>{STATE_MEANING[formal.state] || ''}</div>
              <div style={{ color: '#666', fontSize: 11, marginTop: 6 }}>{formal.note}.</div>
            </div>
            {formal.verification && (
              <div style={{ fontSize: 13 }}>
                <div style={{ color: formal.verification.passed ? GREEN : RED, marginBottom: 4 }}>
                  Checks {formal.verification.passed ? 'passed' : 'failed'} (policy {formal.verification.policy_version})</div>
                {formal.verification.checks.map((c) => (
                  <div key={`${c.kind}-${c.name}`} style={{ color: c.passed ? '#999' : RED }}>
                    {c.passed ? '✓' : '✗'} <Mono>{c.kind}</Mono> {c.name}{c.detail ? `: ${c.detail}` : ''}</div>
                ))}
              </div>
            )}
            {claim.evidence.map((ev) => isCommit(ev) ? (
              <CommitEvidence key={`${ev.id}-${ev.relation}`} ev={ev} mono={fonts.mono} fontSize={13.5}
                borderColor={ev.relation === 'contradicts' ? RED : GREEN} />
            ) : (
              <blockquote key={`${ev.id}-${ev.relation}`} style={{ margin: 0, borderLeft: `3px solid ${ev.relation === 'contradicts' ? RED : GREEN}`,
                padding: '6px 12px', color: '#ccc', fontSize: 13.5, lineHeight: 1.6 }}>
                “{ev.excerpt}”
                <div style={{ marginTop: 4, fontSize: 11, color: '#777', fontFamily: fonts.mono }}>
                  {ev.relation} · {short(ev.source_title, 80)} ({ev.source_id})</div>
              </blockquote>
            ))}
            <div>
              <div style={sectionLabel}>Reviews</div>
              {formal.reviews.length === 0 ? <Note>None yet.</Note> : formal.reviews.map((r, i) => (
                <div key={i} style={{ fontSize: 13, color: '#bbb', padding: '3px 0' }}>
                  <span style={{ color: r.verdict === 'approve' ? GREEN : RED }}>{r.verdict}</span>{' '}
                  <Author name={r.reviewer} kind={r.reviewer_kind} /> on v{r.revision}{r.findings ? ` · ${r.findings}` : ''}
                </div>
              ))}
              <div style={{ marginTop: 8 }}><ReviewBox claimId={claimId} state={formal.state} apiKey={apiKey} onChanged={reload} /></div>
            </div>
            <div>
              <div style={sectionLabel}>Challenges</div>
              {formal.challenges.length === 0 && <Note>No challenges.</Note>}
              {formal.challenges.map((c) => (
                <div key={c.id} style={{ border: '1px solid #222', borderRadius: 10, padding: 12, marginBottom: 10 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
                    <Chip color={c.state === 'open' ? AMBER : c.state === 'upheld' ? RED : '#888'}>{c.state}</Chip>
                    <Chip>{c.kind.replace(/_/g, ' ')}</Chip>{c.blocking && <Chip color={AMBER}>blocking</Chip>}
                    <Author name={c.author} kind={c.author_kind} />{c.revision && <Mono>on v{c.revision}</Mono>}
                  </div>
                  <p style={{ margin: '8px 0', color: '#ddd', fontSize: 14, lineHeight: 1.55 }}>{c.statement}</p>
                  {c.resolution && <Note>Resolution: {c.resolution}</Note>}
                  <Thread target={`challenge:${c.id}`} messages={c.responses} apiKey={apiKey} onChanged={reload}
                    emptyText="No responses yet." />
                </div>
              ))}
              {formal.contradicted_by.length > 0 && (
                <Note tone="error">Contradicted by {formal.contradicted_by.map((x) => (
                  <a key={x.claim_id} href={`/claims/${x.claim_id}`} style={{ color: RED, marginRight: 6 }}>claim {x.claim_id}</a>))}</Note>
              )}
              <div style={{ marginTop: 8 }}><ChallengeForm claimId={claimId} apiKey={apiKey} onChanged={reload} /></div>
            </div>
            <div>
              <div style={sectionLabel}>Reproduction and use</div>
              <VerificationReports target={target} data={formal.verification_reports} apiKey={apiKey} onChanged={reload} />
            </div>
          </div>
        </Panel>

        <Panel title="Discussion" right={<Chip>informal</Chip>}>
          <p style={{ margin: '0 0 12px', color: '#888', fontSize: 12.5 }}>
            {informal.note[0].toUpperCase() + informal.note.slice(1)}. Popularity is not evidence.
          </p>
          <Thread target={target} messages={informal.comments} apiKey={apiKey} onChanged={reload}
            emptyText="No comments yet. Ask a question, suggest an improvement, or point to related evidence." />
        </Panel>
      </div>
    </div>
  );
}

export const sectionLabel = { fontSize: 11, color: '#888', fontFamily: fonts.mono, textTransform: 'uppercase',
  letterSpacing: '0.08em', marginBottom: 6 };
