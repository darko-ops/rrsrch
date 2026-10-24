/**
 * Verification and usage reports on a claim or post (docs/FEEDBACK.md, phase 2).
 *
 *   reproduction   someone tried to reproduce it: reproduced, failed, inconclusive, insufficient evidence
 *   usage          an agent used it in a task: worked, worked with conditions, failed, outdated, missing step, unclear
 *
 * Reports are evidence for reviewers. Submitting one never changes a claim's review state; a repository's policy
 * may ask for independent reproductions before review can make a claim supported.
 */
import React, { useState } from 'react';
import { engine, SIGN_IN, fonts, GREEN, AMBER, RED, Btn, Chip, Note, Mono, inputStyle, when } from './Dashboard';

export const OUTCOMES = {
  reproduction: ['reproduced', 'failed', 'inconclusive', 'insufficient_evidence'],
  usage: ['worked', 'worked_with_conditions', 'failed', 'outdated', 'missing_step', 'unclear'],
};
const TONE = { reproduced: GREEN, worked: GREEN, worked_with_conditions: AMBER, failed: RED, outdated: AMBER,
  missing_step: AMBER };
const label = (s) => s.replace(/_/g, ' ');

// what the form calls each outcome, and the review verdict it is (POST /v1/reviews)
const VERDICT = {
  'reproduction:reproduced': 'reproduced', 'reproduction:failed': 'could_not_reproduce',
  'reproduction:inconclusive': 'inconclusive', 'reproduction:insufficient_evidence': 'insufficient_evidence',
  'usage:worked': 'worked', 'usage:worked_with_conditions': 'worked_with_conditions', 'usage:failed': 'did_not_work',
  'usage:outdated': 'outdated', 'usage:missing_step': 'missing_step', 'usage:unclear': 'unclear',
};

function Summary({ summary }) {
  const parts = Object.entries(summary).flatMap(([ctx, counts]) => Object.entries(counts)
    .filter(([k, n]) => k !== 'independent' && n > 0).map(([k, n]) => ({ ctx, k, n })));
  if (!parts.length) return null;
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {parts.map(({ ctx, k, n }) => <Chip key={`${ctx}-${k}`} color={TONE[k] || '#888'}>{label(k)} · {n}</Chip>)}
      {['reproduction', 'usage'].map((ctx) => summary[ctx]?.independent > 0 && (
        <span key={ctx} style={{ fontSize: 11, color: '#777' }}>{summary[ctx].independent} {ctx} not by the author</span>))}
    </div>
  );
}

function ReportForm({ target, apiKey, onDone }) {
  const [context, setContext] = useState('usage');
  const [outcome, setOutcome] = useState('worked');
  const [f, setF] = useState({ observations: '', method: '', environment: '', conditions: '', limitations: '', artifact: '' });
  const [err, setErr] = useState('');
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const send = async () => {
    const artifacts = f.artifact.trim() ? [{ name: f.artifact.trim().split('/').pop() || 'artifact', url: f.artifact.trim() }] : [];
    const r = await engine('/v1/reviews', { key: apiKey, method: 'POST', body: {     // reproduction and use are reviews
      target, verdict: VERDICT[`${context}:${outcome}`], findings: f.observations, method: f.method,
      environment: f.environment, conditions: f.conditions, limitations: f.limitations, artifacts } });
    if (r.ok) onDone(); else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8, marginTop: 10 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <select aria-label="report kind" value={context} style={inputStyle}
          onChange={(e) => { setContext(e.target.value); setOutcome(OUTCOMES[e.target.value][0]); }}>
          <option value="usage">I used it</option>
          <option value="reproduction">I tried to reproduce it</option>
        </select>
        <select aria-label="outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} style={inputStyle}>
          {OUTCOMES[context].map((o) => <option key={o} value={o}>{label(o)}</option>)}
        </select>
      </div>
      <textarea rows={3} value={f.observations} onChange={set('observations')} style={{ ...inputStyle, resize: 'vertical' }}
        placeholder="What did you do, and what did you see?" />
      <input value={f.method} onChange={set('method')} placeholder="Method (optional)" style={inputStyle} />
      <input value={f.environment} onChange={set('environment')} placeholder="Environment, data, versions (optional)" style={inputStyle} />
      <input value={f.conditions} onChange={set('conditions')} placeholder="Conditions it depended on (optional)" style={inputStyle} />
      <input value={f.limitations} onChange={set('limitations')} placeholder="Limitations (optional)" style={inputStyle} />
      <input value={f.artifact} onChange={set('artifact')} placeholder="Link to an artifact, https:// (optional)" style={inputStyle} />
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn small kind="primary" disabled={!f.observations.trim()} onClick={send}>Submit report</Btn>
        <Btn small onClick={() => onDone(true)}>Cancel</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

export default function VerificationReports({ target, data, apiKey, onChanged }) {
  const [open, setOpen] = useState(false);
  const items = data?.items || [];
  return (
    <div>
      <p style={{ margin: '0 0 8px', color: '#888', fontSize: 12.5 }}>
        Evidence for reviewers from agents and people who reproduced or used this. A report never changes review state by itself.</p>
      {data && <Summary summary={data.summary} />}
      {items.length === 0 && <Note>No reports yet.</Note>}
      {items.map((r) => (
        <div key={r.id} style={{ borderLeft: `3px solid ${TONE[r.outcome] || '#444'}`, padding: '6px 12px', marginTop: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12, color: '#777' }}>
            <span style={{ color: TONE[r.outcome] || '#ddd', fontWeight: 600 }}>{label(r.outcome)}</span>
            <Chip>{r.context}</Chip>
            <span style={{ color: '#ddd' }}>{r.author}</span>
            <Chip color={r.author_kind === 'human' ? '#7aa2ff' : '#9aa0a6'}>{r.author_kind === 'human' ? 'human' : 'agent'}</Chip>
            {!r.independent && <Chip color={AMBER}>by the author</Chip>}
            {r.revision && <Mono>on v{r.revision}</Mono>}
            <span>{when(r.created_at)}</span>
          </div>
          <p style={{ margin: '6px 0 2px', color: '#ddd', fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{r.observations}</p>
          {[['Method', r.method], ['Environment', r.environment], ['Conditions', r.conditions], ['Limitations', r.limitations]]
            .filter(([, v]) => v).map(([k, v]) => (
              <div key={k} style={{ fontSize: 12.5, color: '#999' }}><span style={{ color: '#666' }}>{k}:</span> {v}</div>))}
          {r.artifacts.map((a) => (
            <div key={a.name + (a.url || '')} style={{ fontSize: 12, fontFamily: fonts.mono, color: '#888' }}>
              {a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer nofollow" style={{ color: '#9ab' }}>{a.name}</a> : a.name}
              {a.sha256 && ` · sha256 ${a.sha256.slice(0, 12)}…`}
            </div>
          ))}
        </div>
      ))}
      {apiKey
        ? (open
          ? <ReportForm target={target} apiKey={apiKey} onDone={(cancelled) => { setOpen(false); if (!cancelled) onChanged(); }} />
          : <div style={{ marginTop: 10 }}><Btn small onClick={() => setOpen(true)}>Report a reproduction or use</Btn></div>)
        : <Note>{SIGN_IN} to report.</Note>}
    </div>
  );
}
