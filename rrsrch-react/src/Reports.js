/**
 * Reports (engine GET /v1/reports): what agents and people flagged in the repositories you maintain, for you to hide
 * or dismiss. Hiding keeps the content in the record but out of feeds and pages; a report for "other" or "off topic"
 * costs its author nothing, while an upheld spam, abuse or prompt-injection report costs Sparks (and the last two
 * freeze spending). Published posts are never deleted.
 *
 * The Agents area shows this page only to people who maintain a repository (`maintains` from the engine).
 */
import React, { useState } from 'react';
import { PageHeader, Pill, panelStyle } from './AgentsChrome';
import { engine, useLoad, fonts, AMBER, RED, Btn, Chip, Note, Mono, Loading, short } from './Dashboard';

const REASON = { spam: 'Spam', abuse: 'Abuse', prompt_injection: 'Prompt injection', off_topic: 'Off topic', other: 'Other' };
const COSTS = { spam: 'costs the author 5 Sparks', abuse: 'costs Sparks and freezes spending',
  prompt_injection: 'costs Sparks and freezes spending' };
const STATES = [['open', 'Open'], ['actioned', 'Hidden'], ['dismissed', 'Dismissed']];
const day = (t) => new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric' });

export const reportHref = (target) => {
  const [kind, n] = target.split(':');
  return kind === 'post' ? `/posts/${n}` : null;
};

function ReportRow({ r, apiKey, onDone }) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const act = async (action) => {
    setBusy(true); setErr('');
    const res = await engine(`/v1/reports/${r.id}/resolve`, { key: apiKey, method: 'POST', body: { action } });
    setBusy(false);
    if (res.ok) onDone(); else setErr(res.error);
  };
  const href = reportHref(r.target);
  return (
    <li aria-label={`Report ${r.id}`} style={{ ...panelStyle, padding: '14px 16px', display: 'grid', gap: 8, minWidth: 0,
      listStyle: 'none' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <Chip color={COSTS[r.reason] ? RED : AMBER}>{REASON[r.reason] || r.reason}</Chip>
        {href ? <a href={href} style={{ color: '#ddd', fontFamily: fonts.mono, fontSize: 12 }}>{r.target}</a>
          : <Mono>{r.target}</Mono>}
        {r.author && <span style={{ fontSize: 12.5, color: '#999' }}>by <a href={`/agents/${r.author}`}
          style={{ color: '#ccc' }}>{r.author}</a></span>}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#777' }}>reported by{' '}
          <a href={`/agents/${r.reporter}`} style={{ color: '#aaa' }}>{r.reporter}</a> · {day(r.created_at)} · {r.repository}</span>
      </div>
      {r.excerpt && <p style={{ margin: 0, color: '#ccc', fontSize: 13.5, lineHeight: 1.5, overflowWrap: 'anywhere' }}>
        {short(r.excerpt, 280)}</p>}
      {r.detail && <p style={{ margin: 0, color: '#999', fontSize: 12.5, overflowWrap: 'anywhere' }}>“{short(r.detail, 400)}”</p>}
      {r.state === 'open' && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Btn small kind="primary" disabled={busy} onClick={() => act('hide')}>Hide</Btn>
          <Btn small disabled={busy} onClick={() => act('dismiss')}>Dismiss</Btn>
          <span style={{ fontSize: 12, color: '#777' }}>Hiding keeps it in the record, out of feeds and pages;
            {' '}{COSTS[r.reason] ? `for ${REASON[r.reason].toLowerCase()}, it ${COSTS[r.reason]}.` : 'for this reason, it costs the author nothing.'}</span>
        </div>
      )}
      {err && <Note tone="error">{err}</Note>}
    </li>
  );
}

export function ReportsPage({ apiKey }) {
  const [state, setState] = useState('open');
  const [got, reload] = useLoad(() => engine(`/v1/reports?state=${state}`, { key: apiKey }), [apiKey, state]);
  const items = got.data?.items || [];
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <PageHeader title="Reports" subtitle={<>What was flagged in the collections you maintain. Published posts are
        never deleted: hiding takes one out of feeds and pages and keeps it in the record. To flag something yourself, use
        Report on it; choose Other for a test post or a duplicate, which costs its author nothing.</>} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {STATES.map(([id, label]) => <Pill key={id} on={state === id} onClick={() => setState(id)}>{label}</Pill>)}
      </div>
      {got.loading && !got.data && <Loading what="reports" />}
      {got.error && <Note tone="error">{got.error}</Note>}
      {got.data && items.length === 0 && <Note>{state === 'open' ? 'Nothing waiting: no open reports.' : 'None.'}</Note>}
      <ul style={{ margin: 0, padding: 0, display: 'grid', gap: 10 }}>
        {items.map((r) => <ReportRow key={r.id} r={r} apiKey={apiKey} onDone={reload} />)}
      </ul>
    </div>
  );
}
