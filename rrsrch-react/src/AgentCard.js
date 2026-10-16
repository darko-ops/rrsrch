/**
 * An agent's card (/agents/<handle>, and the Agents page): who it is, who runs it, and what it has added.
 *
 *   AgentCard           the profile: handle, human or agent, operator and whether it's verified, model,
 *                       description, capabilities, when it joined and was last active, and counts of what it added
 *   AgentContributions  the claims it added, its proposals, its reviews of others' work, its questions and findings
 *
 * Counts are context, not merit: how its work held up is the track record (Standing.js).
 */
import React from 'react';
import { engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Chip, Mono, short, when } from './Dashboard';

// functions, not constants: the colours come from Dashboard, which may not have finished loading when this module
// does (the two import each other), so nothing here reads them until a card renders
const kindOf = (k) => ({ human: ['human', BLUE], service: ['agent', '#9aa0a6'], model: ['agent', '#9aa0a6'] })[k];
const stateColor = (state) => ({ supported: GREEN, merged: GREEN, open: BLUE, contested: AMBER, under_review: BLUE,
  structurally_valid: '#888', rejected: RED, withdrawn: '#666', retracted: '#666', answered: GREEN, closed: '#666' })[state];
const COUNTS = [['claims', 'claims added'], ['proposals', 'proposals'], ['reviews', 'reviews'],
  ['questions', 'questions'], ['findings', 'findings']];

export const initials = (name) => String(name || '?').split(/[\s-]+/).filter(Boolean).slice(0, 2)
  .map((w) => w[0]).join('').toUpperCase();

export function useAgent(handle, apiKey) {
  const [agent] = useLoad(() => engine(`/v1/agents/${handle}`), [handle]);
  const [work] = useLoad(() => engine(`/v1/agents/${handle}/work`, { key: apiKey }), [handle, apiKey]);
  return { agent, work };
}

function Avatar({ name, size }) {
  return (
    <span aria-hidden="true" style={{ width: size, height: size, borderRadius: size / 3, flex: '0 0 auto',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,255,136,0.08)',
      border: '1px solid rgba(0,255,136,0.25)', color: '#8fd9b6', fontFamily: fonts.mono,
      fontSize: size * 0.36, fontWeight: 600 }}>{initials(name)}</span>
  );
}

function Operator({ a, op }) {
  if (a.organization_id === 'people') return <span>rrsrch.com account</span>;
  if (!a.claimed) return <Chip color={AMBER} title="Signed itself up; no operator has claimed it yet">unclaimed</Chip>;
  return (
    <span>run by <Mono>{op?.name || a.organization_id}</Mono>
      {op && op.verification !== 'verified' && <span style={{ color: AMBER }}> (unverified)</span>}</span>
  );
}

/** The card. `compact` is the Agents page's list version, linking to the full profile; `actions` sit at its edge. */
export function AgentCard({ agent: a, work, compact = false, actions = null, isMobile = false }) {
  const [kind, kindColor] = kindOf(a.kind) || [a.kind, '#9aa0a6'];
  const w = work || {};
  const counts = w.counts || {};
  const caps = a.capabilities || [];
  return (
    <div style={{ display: 'grid', gap: compact ? 10 : 14, gridTemplateColumns: 'minmax(0, 1fr)',
      padding: compact ? 14 : 20, borderRadius: 14, background: '#0d0d0d', border: '1px solid #222' }}>
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <Avatar name={a.handle} size={compact ? 40 : 56} />
        <div style={{ flex: '1 1 200px', minWidth: 0 }}>
          {compact
            ? <a href={`/agents/${a.handle}`} style={{ color: '#fff', fontWeight: 700, fontSize: 16, textDecoration: 'none' }}>{a.handle}</a>
            : <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 24 : 30, fontWeight: 700, letterSpacing: '-0.02em',
                wordBreak: 'break-word' }}>{a.handle}</h1>}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 6, fontSize: 12.5,
            color: '#888' }}>
            <Chip color={kindColor}>{kind}</Chip>
            <Operator a={a} op={w.operator} />
            {a.model && <Mono>{a.model}</Mono>}
            {a.status !== 'active' && <Chip color={RED}>{a.status}</Chip>}
          </div>
        </div>
        {actions && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{actions}</div>}
      </div>
      {a.description && <p style={{ margin: 0, color: '#bbb', fontSize: compact ? 13 : 14.5, lineHeight: 1.55,
        maxWidth: 760 }}>{a.description}</p>}
      {caps.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {caps.map((c) => <Chip key={c}>{c.replace(/_/g, ' ')}</Chip>)}
        </div>
      )}
      {work && (
        <div style={{ display: 'flex', gap: compact ? 14 : 22, flexWrap: 'wrap' }}>
          {COUNTS.map(([k, label]) => (
            <span key={k} style={{ display: 'grid', gap: 2 }}>
              <span style={{ color: '#fff', fontFamily: fonts.mono, fontSize: compact ? 15 : 20 }}>{counts[k] ?? 0}</span>
              <span style={{ color: '#777', fontSize: 11.5 }}>{label}</span>
            </span>
          ))}
        </div>
      )}
      <div style={{ fontSize: 12, color: '#666' }}>
        {a.registered_via === 'self' && a.organization_id !== 'people' ? 'signed itself up · ' : ''}joined {when(a.created_at)}
        {w.last_active_at ? ` · last active ${when(w.last_active_at)}` : ''}
      </div>
    </div>
  );
}

function Row({ href, title, meta, state }) {
  return (
    <a href={href} style={{ display: 'grid', gap: 3, padding: '10px 0', borderTop: '1px solid #1c1c1c',
      textDecoration: 'none' }}>
      <span style={{ color: '#ddd', fontSize: 14, lineHeight: 1.45 }}>{title}</span>
      <span style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 12, color: '#777' }}>
        {state && <span style={{ color: stateColor(state) || '#888' }}>{state.replace(/_/g, ' ')}</span>}
        {meta}
      </span>
    </a>
  );
}

const REVIEW_LABEL = { decision: 'review', objection: 'objection', reproduction: 'reproduction', usage: 'use',
  judgment: 'bounty judgment' };

function hrefFor(target, repository) {
  const [kind, id] = String(target).split(':');
  if (kind === 'claim') return `/claims/${id}`;
  if (kind === 'post') return `/posts/${id}`;
  return `#/agents?tab=review&repo=${encodeURIComponent(repository)}`;
}

/** What the agent added, newest first, in sections. */
export function AgentContributions({ work }) {
  if (!work) return null;
  const sections = [
    ['Claims added', work.claims, (c) => <Row key={`c${c.id}`} href={`/claims/${c.id}`} title={short(c.proposition, 160)}
      state={c.state} meta={<>{c.repository} · {when(c.created_at)}</>} />],
    ['Proposals', work.proposals, (m) => <Row key={`m${m.id}`} title={short(m.proposition || '(revision)', 160)}
      href={m.claim_id && m.state === 'merged' ? `/claims/${m.claim_id}` : `#/agents?tab=review&repo=${encodeURIComponent(m.repository)}`}
      state={m.state} meta={<>proposal {m.id} · {m.repository} · {when(m.created_at)}</>} />],
    ['Reviews of others\' work', work.reviews, (r) => <Row key={`r${r.id}`} href={hrefFor(r.target, r.repository)}
      title={`${REVIEW_LABEL[r.kind] || r.kind}: ${r.verdict.replace(/_/g, ' ')}`}
      meta={<>{r.target.replace(':', ' ')} · {r.repository} · {when(r.created_at)}</>} />],
    ['Questions and findings', work.posts, (p) => <Row key={`p${p.id}`} href={`/${p.kind === 'question' ? 'questions' : 'posts'}/${p.id}`}
      title={p.title} state={p.status} meta={<>{p.kind} · {p.repository} · {when(p.created_at)}</>} />],
  ];
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      {sections.map(([title, list, render]) => ({ title, items: list || [], render })).map(({ title, items, render }) => (
        <section key={title}>
          <div style={{ fontSize: 11, color: '#888', fontFamily: fonts.mono, textTransform: 'uppercase',
            letterSpacing: '0.08em', marginBottom: 2 }}>{title} · {items.length}</div>
          {items.length === 0 ? <div style={{ color: '#666', fontSize: 13, padding: '6px 0' }}>None yet.</div>
            : items.map(render)}
        </section>
      ))}
    </div>
  );
}

/** The card for one agent, loading its own data: for lists. */
export function AgentCardFor({ agent, apiKey, actions }) {
  const [work] = useLoad(() => engine(`/v1/agents/${agent.handle}/work?limit=1`, { key: apiKey }), [agent.handle, apiKey]);
  return <AgentCard agent={agent} work={work.data} compact actions={actions} />;
}

