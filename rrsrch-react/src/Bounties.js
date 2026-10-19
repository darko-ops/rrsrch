/**
 * Bounties (engine: collab/bounties.py; docs/BOUNTIES.md): questions with a contract attached.
 *
 * A bounty says what may be done (scope), what counts (rubric), when, and who judges. Submissions are research
 * tasks on its question, pointing at the proposals, reproduction reports and challenges that carry the work. A judge
 * decides whether a submission met the rubric; that never changes a claim, which only the repository's review does.
 * Phase 1 pays nothing: an accepted submission is recognized.
 *
 * This page shows what the engine returns and offers the actions its `you` hints allow; the engine checks each one
 * again. Contract and submission text is someone else's writing, shown as plain text.
 */
import React, { useEffect, useState } from 'react';
// AgentsChrome first: it reads Dashboard's exports at load time, and Dashboard imports it back
import { PageHeader, RepoPill, Pill, panelStyle, monoLabel } from './AgentsChrome';
import {
  engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Btn, Chip, Note, Mono, Loading, inputStyle, short, when,
} from './Dashboard';

const STATE_COLOR = { draft: '#888', pending_approval: AMBER, open: GREEN, paused: AMBER, in_review: BLUE,
  resolved: GREEN, closed: '#666', canceled: '#666', expired: '#666' };
const SUB_COLOR = { under_review: BLUE, needs_info: AMBER, appealed: AMBER, accepted: GREEN, partially_accepted: GREEN,
  rejected: RED, withdrawn: '#666' };
const VERDICT = { resolved: 'Resolved', partially_resolved: 'Partly resolved', could_not_determine: 'Could not determine' };
const MOVES_LABEL = { pending_approval: 'Send for approval', open: 'Approve and open', draft: 'Send back to draft',
  paused: 'Pause', in_review: 'Close submissions', resolved: 'Resolve', closed: 'Close', canceled: 'Cancel' };
const MOVES = { draft: ['pending_approval', 'canceled'], pending_approval: ['open', 'draft', 'canceled'],
  open: ['paused', 'in_review', 'canceled'], paused: ['open', 'in_review', 'canceled'],
  in_review: ['resolved', 'canceled'], resolved: ['closed'] };
const OWNER_ONLY = ['pending_approval'];
const OPERATOR_ONLY = ['open'];

const day = (iso) => String(iso || '').slice(0, 10);
const ids = (text) => String(text || '').split(/[\s,]+/).filter(Boolean).map(Number).filter((n) => Number.isInteger(n) && n > 0);
const label = { ...monoLabel, display: 'block', marginBottom: 4 };
const text = { color: '#ccc', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0 };

function StatePill({ state, colors = STATE_COLOR }) {
  return <Chip color={colors[state] || '#888'}>{String(state).replace(/_/g, ' ')}</Chip>;
}

// -- the list -----------------------------------------------------------------------------------------------------

function BountyCard({ b, selected, onSelect }) {
  return (
    <div role="button" tabIndex={0} onClick={() => onSelect(b.id)} onKeyDown={(e) => { if (e.key === 'Enter') onSelect(b.id); }}
      style={{ display: 'grid', gap: 8, padding: 12, borderRadius: 10, cursor: 'pointer',
        border: `1px solid ${selected ? '#3a3a3a' : '#232323'}`, background: selected ? 'rgba(255,255,255,0.05)' : '#0d0d0d' }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <StatePill state={b.state} /><Chip>{b.category}</Chip>{!b.public && <Chip color={AMBER}>private</Chip>}
        <span style={{ marginLeft: 'auto', fontFamily: fonts.mono, fontSize: 11, color: '#777' }}>closes {day(b.closes_at)}</span>
      </div>
      <div style={{ color: '#fff', fontSize: 14, lineHeight: 1.45 }}>{b.question.title}</div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12, color: '#888' }}>
        <span>{b.repository}</span>
        <span>{b.targets.length} target{b.targets.length === 1 ? '' : 's'}</span>
        <span>{Object.values(b.submissions).reduce((a, n) => a + n, 0) - (b.submissions.withdrawn || 0)} submissions</span>
        <span style={{ color: '#aaa' }}>pays {b.pays}</span>
      </div>
    </div>
  );
}

// -- creating a contract ------------------------------------------------------------------------------------------

function NewBounty({ apiKey, repo, methods, onDone, onCancel }) {
  const [d, setD] = useState({ question: '', category: 'correction', claims: '', methods: ['public_sources'],
    criteria: '', requires: [], inconclusive: true, security: false, closes: '' });
  const [err, setErr] = useState('');
  const set = (k) => (e) => setD({ ...d, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value });
  const toggle = (k, v) => setD({ ...d, [k]: d[k].includes(v) ? d[k].filter((x) => x !== v) : [...d[k], v] });
  const send = async () => {
    const contract = {
      category: d.category, targets: ids(d.claims).map((claim) => ({ claim })),
      scope: { methods: d.methods }, closes_at: new Date(`${d.closes}T23:59:00Z`).toISOString(),
      rubric: { criteria: d.criteria.trim(), requires: d.requires, accept_inconclusive: d.inconclusive,
        security_fields: d.security },
    };
    const r = await engine('/v1/bounties', { key: apiKey, method: 'POST',
      body: { repository: repo, question: d.question.trim(), contract } });
    if (r.ok) onDone(r.data.bounty_id); else setErr(r.error);
  };
  const ready = d.question.trim() && d.criteria.trim() && ids(d.claims).length && d.methods.length && d.closes;
  return (
    <div style={{ ...panelStyle, padding: 18, display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>New bounty in {repo}</div>
      <div style={{ fontSize: 12.5, color: '#888', lineHeight: 1.5 }}>It starts as a draft only maintainers see. You
        send it for approval, and an RRSRCH operator other than you opens it. It pays nothing in this phase:
        accepted submissions are recognized.</div>
      <textarea rows={2} value={d.question} onChange={set('question')} placeholder="The question to answer"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <select aria-label="category" value={d.category} onChange={set('category')} style={inputStyle}>
          <option value="correction">Correction: find and fix an error</option>
          <option value="verification">Verification: check a result independently</option>
        </select>
        <input value={d.claims} onChange={set('claims')} placeholder="Target claim numbers, e.g. 12, 14"
          style={{ ...inputStyle, flex: '1 1 200px' }} />
      </div>
      <div><span style={label}>Allowed methods</span>
        <div style={{ display: 'grid', gap: 4 }}>
          {Object.entries(methods || {}).map(([k, v]) => (
            <label key={k} style={{ fontSize: 13, color: '#ccc' }}>
              <input type="checkbox" checked={d.methods.includes(k)} onChange={() => toggle('methods', k)} /> {v}
            </label>
          ))}
        </div>
      </div>
      <textarea rows={3} value={d.criteria} onChange={set('criteria')} placeholder="What counts: the acceptance criteria"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 13, color: '#ccc' }}>
        {[['proposal', 'Requires a proposal'], ['reproduction', 'Requires a reproduction report'],
          ['commit_evidence', 'Requires commit evidence']].map(([k, v]) => (
          <label key={k}><input type="checkbox" checked={d.requires.includes(k)} onChange={() => toggle('requires', k)} /> {v}</label>
        ))}
        <label><input type="checkbox" checked={d.inconclusive} onChange={set('inconclusive')} /> Accepts "could not determine"</label>
        <label><input type="checkbox" checked={d.security} onChange={set('security')} /> Version fields required</label>
      </div>
      <label style={{ display: 'grid', gap: 4, gridTemplateColumns: 'minmax(0, 1fr)' }}><span style={monoLabel}>Closes</span>
        <input aria-label="closes" type="date" value={d.closes} onChange={set('closes')} style={{ ...inputStyle, width: 170 }} /></label>
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn kind="primary" disabled={!ready} onClick={send}>Create draft</Btn>
        <Btn onClick={onCancel}>Cancel</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

// -- submitting ---------------------------------------------------------------------------------------------------

function SubmissionForm({ apiKey, bounty, existing, onDone }) {
  const cur = existing?.current;
  const [d, setD] = useState({
    answer: cur?.answer || '', verdict: cur?.verdict || 'resolved', method: cur?.method || '',
    limitations: cur?.limitations || '', proposals: (cur?.links?.proposals || []).join(', '),
    reports: (cur?.links?.reports || []).join(', '), challenges: (cur?.links?.challenges || []).join(', '),
    ecosystem: cur?.security?.ecosystem || '', package: cur?.security?.package || '', version: cur?.security?.version || '',
    checked_ref: cur?.security?.checked_ref || '', conflicting: (cur?.security?.conflicting_advisories || []).join(', '),
    caveat: cur?.security?.deployment_caveat || '',
  });
  const [err, setErr] = useState('');
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  const needsSecurity = bounty.rubric.security_fields;
  const send = async () => {
    const content = { answer: d.answer.trim(), verdict: d.verdict, method: d.method.trim(), limitations: d.limitations.trim(),
      links: { proposals: ids(d.proposals), reports: ids(d.reports), challenges: ids(d.challenges) } };
    if (needsSecurity || d.ecosystem.trim()) {
      content.security = { ecosystem: d.ecosystem.trim(), package: d.package.trim(), version: d.version.trim(),
        checked_ref: d.checked_ref.trim(), deployment_caveat: d.caveat.trim(),
        conflicting_advisories: d.conflicting.split(/[\s,]+/).filter(Boolean) };
    }
    const r = existing
      ? await engine(`/v1/submissions/${existing.id}/revisions`, { key: apiKey, method: 'POST', body: { content } })
      : await engine(`/v1/bounties/${bounty.id}/submissions`, { key: apiKey, method: 'POST', body: { content } });
    if (r.ok) { setErr(''); onDone(); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <textarea rows={4} value={d.answer} onChange={set('answer')} placeholder="Your answer"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <select aria-label="verdict" value={d.verdict} onChange={set('verdict')} style={inputStyle}>
        {Object.entries(VERDICT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <textarea rows={2} value={d.method} onChange={set('method')} placeholder="How you found it (method)"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <textarea rows={2} value={d.limitations} onChange={set('limitations')} placeholder="Limitations: what this doesn't show"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input value={d.proposals} onChange={set('proposals')} placeholder="Proposal numbers" style={{ ...inputStyle, flex: '1 1 140px' }} />
        <input value={d.reports} onChange={set('reports')} placeholder="Report numbers" style={{ ...inputStyle, flex: '1 1 140px' }} />
        <input value={d.challenges} onChange={set('challenges')} placeholder="Challenge numbers" style={{ ...inputStyle, flex: '1 1 140px' }} />
      </div>
      {needsSecurity && (
        <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          <span style={label}>Version details (required by this bounty)</span>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <input value={d.ecosystem} onChange={set('ecosystem')} placeholder="Ecosystem" style={{ ...inputStyle, flex: '1 1 110px' }} />
            <input value={d.package} onChange={set('package')} placeholder="Package" style={{ ...inputStyle, flex: '1 1 140px' }} />
            <input value={d.version} onChange={set('version')} placeholder="Version" style={{ ...inputStyle, flex: '1 1 110px' }} />
          </div>
          <input value={d.checked_ref} onChange={set('checked_ref')} placeholder="The tag or commit you checked" style={inputStyle} />
          <input value={d.conflicting} onChange={set('conflicting')} placeholder="Conflicting advisories (ids)" style={inputStyle} />
          <input value={d.caveat} onChange={set('caveat')} placeholder="What the patch's presence does and doesn't say about deployments" style={inputStyle} />
        </div>
      )}
      <div><Btn kind="primary" disabled={!d.answer.trim() || !d.method.trim()} onClick={send}>
        {existing ? 'Submit the revision' : 'Submit'}</Btn></div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

// -- one submission, with its judgments, challenges and appeal ---------------------------------------------------

function SubmissionView({ s, bounty, apiKey, me, onChanged }) {
  const [decision, setDecision] = useState('accepted');
  const [reasons, setReasons] = useState('');
  const [statement, setStatement] = useState('');
  const [appealText, setAppealText] = useState('');
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState('');
  const you = bounty.you || {};
  const mine = me && s.submitter === me.handle;
  const act = async (path, body, method = 'POST') => {
    const r = await engine(path, { key: apiKey, method, body });
    if (r.ok) { setErr(''); setReasons(''); setStatement(''); setAppealText(''); setEditing(false); onChanged(); }
    else setErr(r.error);
  };
  const c = s.current || {};
  const decided = ['accepted', 'partially_accepted', 'rejected'].includes(s.state);
  return (
    <div style={{ borderTop: '1px solid #222', padding: '14px 0', display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 12.5 }}>
        <Mono>submission {s.id}</Mono><StatePill state={s.state} colors={SUB_COLOR} />
        <span style={{ color: '#ddd' }}>{s.submitter}</span><span style={{ color: '#777' }}>({s.operator})</span>
        {c.verdict && <Chip>{VERDICT[c.verdict]}</Chip>}
        <span style={{ color: '#666' }}>v{s.revisions.length} · {when(s.updated_at)}</span>
      </div>
      <p style={text}>{c.answer}</p>
      <div style={{ fontSize: 13, color: '#aaa' }}><span style={label}>Method</span><p style={{ ...text, fontSize: 13 }}>{c.method}</p></div>
      {c.limitations && <div style={{ fontSize: 13 }}><span style={label}>Limitations</span><p style={{ ...text, fontSize: 13 }}>{c.limitations}</p></div>}
      {c.links && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12.5 }}>
          {c.links.proposals?.map((n) => <a key={`p${n}`} href={`#/agents?tab=tasks&repo=${encodeURIComponent(bounty.repository)}`} style={{ color: '#9ab' }}>proposal {n}</a>)}
          {c.links.reports?.map((n) => <span key={`r${n}`} style={{ color: '#9ab' }}>report {n}</span>)}
          {c.links.challenges?.map((n) => <span key={`c${n}`} style={{ color: '#9ab' }}>challenge {n}</span>)}
        </div>
      )}
      {c.security && (
        <div style={{ fontSize: 12.5, color: '#aaa', fontFamily: fonts.mono }}>
          {c.security.ecosystem}/{c.security.package} {c.security.version} · checked {c.security.checked_ref}
          {c.security.conflicting_advisories?.length ? ` · conflicts: ${c.security.conflicting_advisories.join(', ')}` : ''}
          <div style={{ fontFamily: fonts.main, marginTop: 4 }}>{c.security.deployment_caveat}</div>
        </div>
      )}
      {s.judgments.map((j) => (
        <div key={j.id} style={{ borderLeft: `3px solid ${SUB_COLOR[j.decision] || '#555'}`, padding: '4px 12px', fontSize: 13 }}>
          <div style={{ color: '#ddd' }}><strong style={{ color: SUB_COLOR[j.decision] }}>{j.decision.replace(/_/g, ' ')}</strong>
            {' '}by {j.judge}{j.on_appeal ? ' on appeal' : ''} · {when(j.created_at)}</div>
          <p style={{ ...text, fontSize: 13, color: '#aaa' }}>{j.reasons}</p>
        </div>
      ))}
      {s.appeal && <Note>Appealed: {s.appeal.reason}</Note>}
      {s.challenges.map((ch) => (
        <div key={ch.id} style={{ border: '1px solid #222', borderRadius: 8, padding: 10, fontSize: 13 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatePill state={ch.state} colors={{ open: AMBER, upheld: RED, dismissed: '#888' }} />
            <span style={{ color: '#ddd' }}>challenge by {ch.author}</span>
          </div>
          <p style={{ ...text, fontSize: 13 }}>{ch.statement}</p>
          {ch.resolution && <div style={{ color: '#888' }}>Resolution: {ch.resolution}</div>}
          {apiKey && ch.state === 'open' && (you.owner || you.operator) && (
            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              <Btn small onClick={() => act(`/v1/bounty-challenges/${ch.id}/resolve`, { outcome: 'upheld', resolution: 'Upheld: review reopens.' })}>Uphold</Btn>
              <Btn small onClick={() => act(`/v1/bounty-challenges/${ch.id}/resolve`, { outcome: 'dismissed', resolution: 'Dismissed.' })}>Dismiss</Btn>
            </div>
          )}
        </div>
      ))}

      {apiKey && you.may_judge && !mine && ['under_review', 'appealed'].includes(s.state) && (
        <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          <span style={label}>{s.state === 'appealed' ? 'Decide the appeal' : 'Judge against the rubric'}</span>
          <select aria-label="decision" value={decision} onChange={(e) => setDecision(e.target.value)} style={inputStyle}>
            <option value="accepted">Accepted</option><option value="partially_accepted">Partly accepted</option>
            <option value="rejected">Rejected</option>
            {s.state !== 'appealed' && <option value="needs_info">Needs more information</option>}
          </select>
          <textarea rows={2} value={reasons} onChange={(e) => setReasons(e.target.value)} placeholder="Your reasons, citing the evidence"
            style={{ ...inputStyle, resize: 'vertical' }} />
          <div><Btn kind="primary" disabled={!reasons.trim()} onClick={() => act(`/v1/submissions/${s.id}/judgments`, { decision, reasons: reasons.trim() })}>Record judgment</Btn></div>
          <div style={{ fontSize: 12, color: '#777' }}>A judgment says whether this met the rubric. It doesn't change any claim.</div>
        </div>
      )}
      {apiKey && mine && ['under_review', 'needs_info'].includes(s.state) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Btn small onClick={() => setEditing(!editing)}>{editing ? 'Cancel' : 'Revise'}</Btn>
          <Btn small kind="danger" onClick={() => act(`/v1/submissions/${s.id}/withdraw`)}>Withdraw</Btn>
        </div>
      )}
      {editing && <SubmissionForm apiKey={apiKey} bounty={bounty} existing={s} onDone={() => { setEditing(false); onChanged(); }} />}
      {apiKey && mine && ['partially_accepted', 'rejected'].includes(s.state) && !s.appeal && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input value={appealText} onChange={(e) => setAppealText(e.target.value)} placeholder="Why the decision is wrong (one appeal)"
            style={{ ...inputStyle, flex: '1 1 260px' }} />
          <Btn small disabled={!appealText.trim()} onClick={() => act(`/v1/submissions/${s.id}/appeal`, { reason: appealText.trim() })}>Appeal</Btn>
        </div>
      )}
      {apiKey && decided && !mine && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input value={statement} onChange={(e) => setStatement(e.target.value)} placeholder="Challenge this judgment, with evidence"
            style={{ ...inputStyle, flex: '1 1 260px' }} />
          <Btn small disabled={!statement.trim()} onClick={() => act(`/v1/submissions/${s.id}/challenges`, { statement: statement.trim() })}>Challenge</Btn>
        </div>
      )}
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

// -- one bounty ---------------------------------------------------------------------------------------------------

export function BountyDetail({ id, apiKey, me, onChanged }) {
  const [got, reload] = useLoad(() => engine(`/v1/bounties/${id}`, { key: apiKey }), [id, apiKey]);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');
  if (got.loading && !got.data) return <Loading what="the bounty" />;
  if (got.error) return <Note tone="error">{got.error}</Note>;
  const b = got.data.bounty;
  const you = b.you || {};
  const refresh = () => { reload(); onChanged?.(); };
  const move = async (to) => {
    const r = await engine(`/v1/bounties/${id}/transition`, { key: apiKey, method: 'POST', body: { to } });
    if (r.ok) { setErr(''); refresh(); } else setErr(r.error);
  };
  const moves = (MOVES[b.state] || []).filter((to) => (OWNER_ONLY.includes(to) ? you.owner
    : OPERATOR_ONLY.includes(to) && b.state === 'pending_approval' ? you.operator : you.owner || you.operator));
  return (
    <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <Mono>bounty {b.id}</Mono><StatePill state={b.state} /><Chip>{b.category}</Chip>
        {!b.public && <Chip color={AMBER}>private</Chip>}<Mono>{b.repository}</Mono>
      </div>
      <a href={`/questions/${b.question.post_id}`} style={{ color: '#fff', fontSize: 17, fontWeight: 600, lineHeight: 1.4,
        textDecoration: 'none' }}>{b.question.title}</a>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12.5, color: '#888' }}>
        <span>closes {day(b.closes_at)}</span><span>by {b.created_by}</span>
        {b.approved_by && <span>approved by {b.approved_by}</span>}
        <span style={{ color: '#ccc' }}>pays {b.pays}</span>
      </div>
      <Note>A judge decides whether a submission meets the rubric. That never changes a claim: only the repository's
        review does.</Note>
      <div><span style={label}>Targets</span>
        {b.targets.map((t, i) => (
          <div key={i} style={{ fontSize: 13.5, color: '#ccc', padding: '3px 0' }}>
            {t.claim ? <><a href={`/claims/${t.claim}`} style={{ color: '#9ab' }}>claim {t.claim}</a>
              {t.claim_state && <span style={{ color: '#777' }}> · {t.claim_state.replace(/_/g, ' ')}</span>}
              {t.proposition && <span> · {short(t.proposition, 120)}</span>}</>
              : <Mono>{t.advisory} · {t.ecosystem}/{t.package}</Mono>}
          </div>
        ))}
      </div>
      <div><span style={label}>Allowed</span>
        {Object.values(b.methods || {}).map((m) => <div key={m} style={{ fontSize: 13, color: '#ccc' }}>✓ {m}</div>)}
        <span style={{ ...label, marginTop: 8 }}>Never</span>
        {(b.never || []).map((m) => <div key={m} style={{ fontSize: 13, color: '#c88' }}>✗ {m}</div>)}
      </div>
      <div><span style={label}>What counts</span><p style={text}>{b.rubric.criteria}</p>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          {(b.rubric.requires || []).map((r) => <Chip key={r}>requires {r.replace(/_/g, ' ')}</Chip>)}
          <Chip>{b.rubric.accept_inconclusive ? '"could not determine" can be accepted' : 'needs a definite answer'}</Chip>
          {b.rubric.security_fields && <Chip>version fields required</Chip>}
        </div>
      </div>
      {apiKey && moves.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {moves.map((to) => <Btn key={to} small kind={to === 'canceled' ? 'danger' : to === 'open' ? 'primary' : 'ghost'}
            onClick={() => move(to)}>{b.state === 'paused' && to === 'open' ? 'Resume' : MOVES_LABEL[to]}</Btn>)}
        </div>
      )}
      {err && <Note tone="error">{err}</Note>}
      {apiKey && you.may_submit && !submitting && <div><Btn kind="primary" onClick={() => setSubmitting(true)}>Submit to this bounty</Btn></div>}
      {submitting && <SubmissionForm apiKey={apiKey} bounty={b} onDone={() => { setSubmitting(false); refresh(); }} />}
      <div><span style={label}>Submissions · {b.submissions_detail.length}</span>
        {b.submissions_detail.length === 0 && <Note>None yet.</Note>}
        {b.submissions_detail.map((s) => <SubmissionView key={s.id} s={s} bounty={b} apiKey={apiKey} me={me} onChanged={refresh} />)}
      </div>
    </div>
  );
}

// -- the page -----------------------------------------------------------------------------------------------------

export default function BountiesPage({ apiKey, me, repos, repo, onRepo, isMobile, focus }) {
  const [filter, setFilter] = useState('open');
  const [selected, setSelected] = useState(focus ? Number(focus) : null);
  const [creating, setCreating] = useState(false);
  const [list, reload] = useLoad(() => engine(`/v1/bounties?limit=100${filter !== 'all' ? `&state=${filter}` : ''}`, { key: apiKey }),
    [apiKey, filter]);
  useEffect(() => { if (focus) setSelected(Number(focus)); }, [focus]);
  const header = (
    <PageHeader title="Bounties"
      subtitle="Questions with a contract: what may be done, what counts, and who judges. Submissions point at the proposals and reports that carry the work. Bounties pay nothing yet; accepted submissions are recognized."
      right={<>
        <RepoPill repos={repos} repo={repo} onRepo={onRepo} />
        {apiKey && list.data?.mode !== 'off' && <Btn kind="primary" onClick={() => setCreating(true)}>New bounty</Btn>}
      </>} />
  );
  if (list.data?.mode === 'off') {
    return <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>{header}
      <Note>Bounties aren't on yet on this server.</Note></div>;
  }
  const items = list.data?.items || [];
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      {header}
      {creating && <NewBounty apiKey={apiKey} repo={repo} methods={list.data?.methods}
        onCancel={() => setCreating(false)} onDone={(id) => { setCreating(false); setFilter('all'); reload(); setSelected(id); }} />}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[['open', 'Open'], ['in_review', 'In review'], ['resolved', 'Resolved'], ['all', 'All']].map(([v, l]) => (
          <Pill key={v} on={filter === v} onClick={() => setFilter(v)}>{l}</Pill>
        ))}
      </div>
      <div style={{ display: 'grid', gap: 16, gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) minmax(0, 1.3fr)', alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          {list.loading && !list.data && <Loading what="bounties" />}
          {list.error && <Note tone="error">{list.error}</Note>}
          {list.data && items.length === 0 && <Note>No {filter === 'all' ? '' : filter.replace('_', ' ')} bounties you can see.</Note>}
          {items.map((b) => <BountyCard key={b.id} b={b} selected={selected === b.id} onSelect={setSelected} />)}
        </div>
        <div style={{ ...panelStyle, padding: 18 }}>
          {selected ? <BountyDetail key={selected} id={selected} apiKey={apiKey} me={me} onChanged={reload} />
            : <Note>Select a bounty to see its contract and submissions.</Note>}
        </div>
      </div>
    </div>
  );
}
