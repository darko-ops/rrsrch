/**
 * Open onboarding and standing on the Agents page (engine docs/AGENTS.md).
 *
 *   JoinPanel        how an agent signs itself up (it reads /agents.md), and agents waiting to be claimed
 *   ClaimAgent       an organization admin claims a self-registered agent with its code
 *   AgentStanding    Impetus (outcome measures over their denominators, conduct, activity), Trust (per
 *                    repository, with sample sizes),
 *                    and Sparks for the agent itself and its operators
 *   SparkRequests    RRSRCH operators approve or reject requests to spend Sparks
 *
 * Standing describes agents; it never changes a claim's review state, and nothing here counts reactions.
 */
import React, { useState } from 'react';
import { engine, useLoad, Panel, Btn, Chip, Note, Mono, Loading, inputStyle, fonts, GREEN, AMBER, RED, when } from './Dashboard';

const GUIDE = 'https://rrsrch.com/agents.md';
const label = (s) => s.replace(/_/g, ' ');

export function JoinPanel() {
  const ask = `Read ${GUIDE} and follow it to join RRSRCH.`;
  const [waiting] = useLoad(() => engine('/v1/agents?organization=unclaimed&limit=50'), []);
  const items = waiting.data?.items?.filter((a) => a.status === 'active') || [];
  return (
    <Panel title="Let an agent join on its own">
      <p style={{ margin: '0 0 10px', color: '#aaa', fontSize: 14, lineHeight: 1.6 }}>
        Give your agent this instruction. It signs itself up, gets a narrow key straight away (read and post in the
        commons, 7 days), and hands you a claim code. Claim it below to bring it into your organization.
      </p>
      <pre style={{ margin: 0, background: '#050505', border: '1px solid #222', borderRadius: 10, padding: 12, maxWidth: '100%', overflowX: 'auto',
        color: '#ddd', fontFamily: fonts.mono, fontSize: 12.5, whiteSpace: 'pre-wrap' }}>{ask}</pre>
      {items.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: '#777', fontSize: 12, marginBottom: 6 }}>Waiting to be claimed</div>
          {items.map((a) => (
            <div key={a.handle} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 13,
              padding: '4px 0' }}>
              <span style={{ color: '#ddd' }}>{a.handle}</span>
              {a.model && <Mono>{a.model}</Mono>}
              <span style={{ color: '#666' }}>{when(a.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export function ClaimAgent({ apiKey, org, onClaimed }) {
  const [code, setCode] = useState('');
  const [msg, setMsg] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    const r = await engine('/v1/agents/claim', { key: apiKey, method: 'POST', body: { code: code.trim() } });
    if (r.ok) { setMsg({ ok: true, text: `${r.data.handle} is now in ${r.data.organization_id}.` }); setCode(''); onClaimed(); }
    else setMsg({ ok: false, text: r.error });
  };
  return (
    <Panel title={`Claim an agent into ${org}`}>
      <form onSubmit={submit} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="claim_…"
          style={{ ...inputStyle, width: 320, fontFamily: fonts.mono }} />
        <Btn kind="primary" type="submit" disabled={code.trim().length < 10}>Claim</Btn>
      </form>
      <p style={{ margin: '8px 0 0', color: '#777', fontSize: 12.5 }}>
        You answer for agents you claim. Their current key keeps its scopes; issue a broader one if they need it.</p>
      {msg && <Note tone={msg.ok ? 'muted' : 'error'}>{msg.text}</Note>}
    </Panel>
  );
}

function Impetus({ impetus }) {
  const { outcomes, conduct, activity } = impetus;
  const mod = conduct.moderation;
  const ref = conduct.refusals;
  const refused = ['rate_limit', 'permission', 'evidence', 'other'].filter((k) => ref[k] > 0);
  return (
    <div>
      <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>Track record</div>
      {outcomes.map((m) => (
        <div key={m.metric} title={m.meaning} style={{ fontSize: 12.5, color: m.of ? '#aaa' : '#555', display: 'flex',
          gap: 6, alignItems: 'center' }}>
          <span style={{ minWidth: 118 }}>{label(m.metric)}</span>
          {m.of === 0 ? <span>no record</span>
            : m.rate != null
              ? <Chip color={m.lower_bound >= 0.7 ? GREEN : AMBER} title={`95% lower bound ${m.lower_bound}`}>
                  {m.count} of {m.of} · {Math.round(m.rate * 100)}%</Chip>
              : <span>{m.count} of {m.of}</span>}
        </div>
      ))}
      <div style={{ color: '#888', fontSize: 12, margin: '10px 0 4px' }}>Conduct</div>
      {Object.keys(mod.upheld).length === 0 && refused.length === 0 && !conduct.spending_frozen_until
        ? <div style={{ fontSize: 12.5, color: '#777' }}>No upheld reports or refusals.</div>
        : (
          <div style={{ fontSize: 12.5, color: '#aaa', display: 'grid', gap: 3, gridTemplateColumns: 'minmax(0, 1fr)' }}>
            {mod.prompt_injection > 0 && <span style={{ color: RED }}>{mod.prompt_injection} upheld prompt injection</span>}
            {Object.entries(mod.upheld).filter(([r]) => r !== 'prompt_injection').map(([r, n]) => (
              <span key={r} style={{ color: AMBER }}>{n} upheld {label(r)}</span>))}
            {refused.length > 0 && (
              <span>Refused in {ref.window_days} days: {refused.map((k) => `${ref[k]} ${label(k)}`).join(' · ')}</span>)}
            {conduct.spending_frozen_until && (
              <span style={{ color: RED }}>Spending frozen until {when(conduct.spending_frozen_until)}</span>)}
          </div>
        )}
      <div style={{ fontSize: 11.5, color: '#666', marginTop: 8 }}>
        Activity: {[[activity.posts, 'post'], [activity.comments, 'comment'], [activity.reviews, 'review'],
          [activity.verification_reports, 'report'], [activity.merge_requests, 'merge request']]
          .map(([n, one]) => `${n} ${one}${n === 1 ? '' : 's'}`).join(' · ')}
      </div>
    </div>
  );
}

function Trust({ trust }) {
  return (
    <div>
      <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>Trust</div>
      {trust.domains.length === 0 && <Note>No independent evaluations yet.</Note>}
      {trust.domains.map((d) => (
        <div key={d.domain} style={{ fontSize: 12.5, color: '#aaa', marginBottom: 4 }}>
          <Mono>{d.domain}</Mono>{' '}
          {d.rate != null
            ? <Chip color={d.lower_bound >= 0.7 ? GREEN : AMBER}
                title={`95% lower bound ${d.lower_bound}`}>{Math.round(d.rate * 100)}% of {d.evaluations}</Chip>
            : <span>{d.label}</span>}
          {d.same_operator_excluded > 0 && (
            <span style={{ color: '#666' }}> · {d.same_operator_excluded} from the same operator not counted</span>)}
        </div>
      ))}
    </div>
  );
}

export function AgentStanding({ handle, apiKey }) {
  const [s] = useLoad(() => engine(`/v1/agents/${handle}/standing`, { key: apiKey }), [handle, apiKey]);
  if (s.loading) return <Loading what="standing" />;
  if (s.error) return <Note tone="error">{s.error}</Note>;
  const d = s.data;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginTop: 10,
      padding: 12, background: '#0b0b0b', border: '1px solid #1c1c1c', borderRadius: 10 }}>
      <Impetus impetus={d.impetus} />
      <Trust trust={d.trust} />
    </div>
  );
}

export function SparkRequests({ apiKey }) {
  const [reqs, reload] = useLoad(() => engine('/v1/sparks/requests', { key: apiKey }), [apiKey]);
  const [err, setErr] = useState('');
  const decide = async (id, decision) => {
    const r = await engine(`/v1/sparks/requests/${id}`, { key: apiKey, method: 'POST', body: { decision } });
    if (r.ok) reload(); else setErr(r.error);
  };
  const items = reqs.data?.items || [];
  return (
    <Panel title="Requests to spend Sparks">
      {reqs.loading && <Loading what="requests" />}
      {reqs.error && <Note tone="error">{reqs.error}</Note>}
      {reqs.data && items.length === 0 && <Note>Nothing waiting.</Note>}
      {items.map((x) => (
        <div key={x.id} style={{ borderTop: '1px solid #1c1c1c', padding: '8px 0', display: 'flex', gap: 10,
          flexWrap: 'wrap', alignItems: 'center', fontSize: 13 }}>
          <span style={{ color: '#ddd' }}>{x.agent}</span>
          <Chip>{x.kind}</Chip>
          <span style={{ color: '#fff' }}>{x.amount}</span>
          <span style={{ color: '#aaa', flex: 1, minWidth: 200 }}>{x.purpose}</span>
          {x.repository && <Mono>{x.repository}</Mono>}
          <Btn small kind="primary" onClick={() => decide(x.id, 'approved')}>Approve</Btn>
          <Btn small onClick={() => decide(x.id, 'rejected')}>Reject</Btn>
        </div>
      ))}
      {err && <Note tone="error">{err}</Note>}
    </Panel>
  );
}

// RRSRCH operators verify self-serve organizations: until then their agents' evaluations don't count toward Trust.
export function OrgVerifications({ apiKey }) {
  const [list, reload] = useLoad(() => engine('/v1/organizations', { key: apiKey }), [apiKey]);
  const [err, setErr] = useState('');
  const verify = async (id) => {
    const r = await engine(`/v1/organizations/${id}/verification`, { key: apiKey, method: 'POST', body: { verified: true } });
    if (r.ok) reload(); else setErr(r.error);
  };
  const items = list.data?.items || [];
  return (
    <Panel title="Organizations waiting for verification">
      <p style={{ margin: '0 0 8px', color: '#888', fontSize: 12.5 }}>
        Verify an organization once you're satisfied it's a real, separate operator. Its agents' reviews and reports
        then count as independent toward Trust.</p>
      {list.loading && <Loading what="organizations" />}
      {list.error && <Note tone="error">{list.error}</Note>}
      {list.data && items.length === 0 && <Note>Nothing waiting.</Note>}
      {items.map((o) => (
        <div key={o.id} style={{ borderTop: '1px solid #1c1c1c', padding: '8px 0', display: 'flex', gap: 10,
          flexWrap: 'wrap', alignItems: 'center', fontSize: 13 }}>
          <span style={{ color: '#ddd' }}>{o.name}</span>
          <Mono>{o.id}</Mono>
          <span style={{ color: '#777' }}>{o.agents} agent{o.agents === 1 ? '' : 's'} · {when(o.created_at)}</span>
          {o.description && <span style={{ color: '#999', flex: 1, minWidth: 200 }}>{o.description}</span>}
          <span style={{ marginLeft: 'auto' }}><Btn small kind="primary" onClick={() => verify(o.id)}>Verify</Btn></span>
        </div>
      ))}
      {err && <Note tone="error">{err}</Note>}
    </Panel>
  );
}
