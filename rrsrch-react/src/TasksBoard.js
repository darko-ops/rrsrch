/**
 * Tasks as a board (design handoff: agents pages §5, option 5a).
 *
 * Six lifecycle columns, one card per task. "Take it" on an authorized card assigns it to you; clicking a card
 * opens today's TaskDetail beside the board. "List" switches to today's list view. Failed, canceled and expired
 * tasks live under Archive.
 */
import React, { useState } from 'react';
// AgentsChrome first: it reads Dashboard's exports at load time, and Dashboard imports it back
import { PageHeader, RepoPill, Pill, panelStyle, monoLabel } from './AgentsChrome';
import {
  engine, useLoad, fonts, GREEN, AMBER, RED, BLUE, Btn, Note, Loading, inputStyle, Tasks, TaskDetail,
} from './Dashboard';

const PURPLE = '#c9a0ff';
export const COLUMNS = [
  { state: 'proposed', label: 'Proposed', color: '#888' },
  { state: 'authorized', label: 'Authorized', color: AMBER },
  { state: 'assigned', label: 'Assigned', color: PURPLE },
  { state: 'in_progress', label: 'In progress', color: BLUE },
  { state: 'awaiting_review', label: 'Awaiting review', color: AMBER },
  { state: 'completed', label: 'Completed', color: GREEN },
];
const ARCHIVED = ['failed', 'canceled', 'expired'];

// a budget may be a number or an object such as {sparks: 50}
export function budgetOf(b) {
  if (b == null) return null;
  if (typeof b === 'number') return b;
  if (typeof b === 'object') {
    const v = b.sparks ?? b.amount ?? b.budget ?? Object.values(b).find((x) => typeof x === 'number');
    return typeof v === 'number' ? v : null;
  }
  const n = Number(b);
  return Number.isFinite(n) ? n : null;
}

function dueLabel(due) {
  if (!due) return null;
  const days = (new Date(due).getTime() - Date.now()) / 86400000;
  const text = days < 0 ? 'overdue' : days < 1 ? 'due today' : `due in ${Math.ceil(days)} d`;
  return { text, soon: days <= 2 };
}

function TaskCard({ t, me, selected, onSelect, onTake }) {
  const budget = budgetOf(t.budget);
  const due = dueLabel(t.due_at);
  const mine = me && t.assignee === me.handle;
  return (
    <div role="button" tabIndex={0} onClick={() => onSelect(t.id)} onKeyDown={(e) => { if (e.key === 'Enter') onSelect(t.id); }}
      style={{ display: 'grid', gap: 7, padding: 10, borderRadius: 10, cursor: 'pointer',
        border: `1px solid ${selected ? '#3a3a3a' : '#232323'}`, background: selected ? 'rgba(255,255,255,0.05)' : '#0d0d0d' }}>
      <div style={{ fontSize: 12.5, color: '#fff', lineHeight: 1.45 }}>{t.question}</div>
      <div style={{ fontSize: 11.5, color: '#888', lineHeight: 1.4 }}>→ {t.deliverable}</div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontFamily: fonts.mono, fontSize: 10.5, color: '#666' }}>#{t.id}</span>
        {budget != null && (
          <span style={{ border: `1px solid ${AMBER}55`, color: AMBER, borderRadius: 999, padding: '1px 7px',
            fontFamily: fonts.mono, fontSize: 10.5 }}>{budget} ✦</span>
        )}
        {due && <span style={{ fontFamily: fonts.mono, fontSize: 10.5, color: due.soon ? RED : '#888' }}>{due.text}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5 }}>
        {mine ? <span style={{ color: GREEN }}>you</span>
          : t.assignee ? <span style={{ color: '#aaa' }}>{t.assignee}</span>
            : <span style={{ color: '#777' }}>by {t.created_by}</span>}
        {t.state === 'authorized' && onTake && (
          <button type="button" onClick={(e) => { e.stopPropagation(); onTake(t.id); }} style={{ marginLeft: 'auto',
            background: 'transparent', color: GREEN, border: `1px solid ${GREEN}66`, borderRadius: 7, padding: '3px 9px',
            fontSize: 11.5, cursor: 'pointer', fontFamily: fonts.main }}>Take it</button>
        )}
      </div>
    </div>
  );
}

function ProposeForm({ apiKey, repo, onDone, onCancel }) {
  const [d, setD] = useState({ question: '', deliverable: '', budget: '', due: '' });
  const [err, setErr] = useState('');
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value });
  const send = async () => {
    const body = { question: d.question.trim(), deliverable: d.deliverable.trim(),
      budget: d.budget ? { sparks: Number(d.budget) } : {}, due_at: d.due ? new Date(d.due).toISOString() : null };
    const r = await engine(`/v1/repos/${repo}/tasks`, { key: apiKey, method: 'POST', body });
    if (r.ok) onDone(r.data.task_id); else setErr(r.error);
  };
  return (
    <div style={{ ...panelStyle, padding: 18, display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>Propose a task</div>
      <div style={{ fontSize: 12.5, color: '#888' }}>A maintainer authorizes it before anyone can take it.</div>
      <textarea rows={2} value={d.question} onChange={set('question')} placeholder="Question to investigate"
        style={{ ...inputStyle, resize: 'vertical' }} />
      <input value={d.deliverable} onChange={set('deliverable')} placeholder="Deliverable that would answer it" style={inputStyle} />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <label style={{ display: 'grid', gap: 4, gridTemplateColumns: 'minmax(0, 1fr)' }}><span style={monoLabel}>Budget</span>
          <input type="number" min="0" value={d.budget} onChange={set('budget')} placeholder="✦" style={{ ...inputStyle, width: 120 }} /></label>
        <label style={{ display: 'grid', gap: 4, gridTemplateColumns: 'minmax(0, 1fr)' }}><span style={monoLabel}>Due</span>
          <input type="date" value={d.due} onChange={set('due')} style={{ ...inputStyle, width: 170 }} /></label>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Btn kind="primary" disabled={!d.question.trim() || !d.deliverable.trim()} onClick={send}>Propose</Btn>
        <Btn onClick={onCancel}>Cancel</Btn>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function Segmented({ value, options, onChange }) {
  return (
    <span style={{ display: 'inline-flex', border: '1px solid #333', borderRadius: 8, overflow: 'hidden' }}>
      {options.map(([v, l]) => (
        <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)} style={{
          padding: '7px 12px', fontSize: 12.5, border: 'none', cursor: 'pointer', fontFamily: fonts.main,
          background: value === v ? 'rgba(255,255,255,0.08)' : 'transparent', color: value === v ? '#fff' : '#888',
        }}>{l}</button>
      ))}
    </span>
  );
}

export default function TasksBoard({ apiKey, me, repos, repo, onRepo, isMobile }) {
  const [view, setView] = useState('board');
  const [filter, setFilter] = useState('all');           // all | mine | open | archive
  const [selected, setSelected] = useState(null);
  const [proposing, setProposing] = useState(false);
  const [err, setErr] = useState('');
  const [list, reload] = useLoad(() => engine(`/v1/repos/${repo}/tasks?limit=200`, { key: apiKey }), [repo, apiKey]);
  const take = async (id) => {
    const r = await engine(`/v1/tasks/${id}/transition`, { key: apiKey, method: 'POST', body: { to: 'assigned' } });
    if (r.ok) { setErr(''); reload(); } else setErr(r.error);
  };
  const all = list.data?.items || [];
  const shown = all.filter((t) => (filter === 'archive' ? ARCHIVED.includes(t.state) : !ARCHIVED.includes(t.state))
    && (filter !== 'mine' || (me && t.assignee === me.handle)) && (filter !== 'open' || t.state === 'authorized'));
  const header = (
    <PageHeader title="Tasks"
      subtitle="Research questions with a deliverable. Maintainers authorize them; anyone with the right scope can take one."
      right={<>
        <Segmented value={view} onChange={setView} options={[['board', 'Board'], ['list', 'List']]} />
        <RepoPill repos={repos} repo={repo} onRepo={onRepo} />
        {apiKey && <Btn kind="primary" onClick={() => setProposing(true)}>Propose task</Btn>}
      </>} />
  );
  if (view === 'list') {
    return <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>{header}<Tasks apiKey={apiKey} repo={repo} me={me} isMobile={isMobile} /></div>;
  }
  const columns = filter === 'archive'
    ? ARCHIVED.map((s) => ({ state: s, label: s, color: s === 'failed' ? RED : '#666' }))
    : COLUMNS;
  return (
    <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      {header}
      {proposing && (
        <ProposeForm apiKey={apiKey} repo={repo} onCancel={() => setProposing(false)}
          onDone={(id) => { setProposing(false); reload(); setSelected(id); }} />
      )}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <Pill on={filter === 'all'} onClick={() => setFilter('all')}>All</Pill>
        {me && <Pill on={filter === 'mine'} onClick={() => setFilter('mine')}>Assigned to me</Pill>}
        <Pill on={filter === 'open'} onClick={() => setFilter('open')}>Up for grabs</Pill>
        <Pill on={filter === 'archive'} onClick={() => setFilter('archive')}>Archive</Pill>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#666' }}>Failed, canceled and expired tasks are under Archive.</span>
      </div>
      {list.loading && !list.data && <Loading what="tasks" />}
      {list.error && <Note tone="error">{list.error}</Note>}
      {err && <Note tone="error">{err}</Note>}
      <div style={{ overflowX: 'auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(${columns.length}, minmax(${isMobile ? 220 : 0}px, 1fr))`,
          gap: 10, minWidth: isMobile ? columns.length * 230 : 0 }}>
          {columns.map((c) => {
            const cards = shown.filter((t) => t.state === c.state);
            return (
              <section key={c.state} aria-label={c.label} style={{ background: 'rgba(10,10,10,0.45)', border: '1px solid #1e1e1e',
                borderRadius: 12, padding: 10, minHeight: 440, display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)', gap: 8, alignContent: 'start' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 2px 4px' }}>
                  <span style={{ width: 7, height: 7, borderRadius: 999, background: c.color }} />
                  <span style={{ ...monoLabel, color: '#aaa', whiteSpace: 'nowrap' }}>{c.label}</span>
                  <span style={{ marginLeft: 'auto', fontFamily: fonts.mono, fontSize: 11, color: '#666' }}>{cards.length}</span>
                </div>
                {cards.map((t) => (
                  <TaskCard key={t.id} t={t} me={me} selected={selected === t.id} onSelect={setSelected}
                    onTake={apiKey ? take : null} />
                ))}
              </section>
            );
          })}
        </div>
      </div>
      {selected && (
        <div style={{ ...panelStyle, padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ color: '#fff', fontWeight: 700, fontSize: 15 }}>Task #{selected}</span>
            <span style={{ marginLeft: 'auto' }}><Btn small onClick={() => setSelected(null)}>Close</Btn></span>
          </div>
          <TaskDetail id={selected} apiKey={apiKey} me={me} onChanged={reload} />
        </div>
      )}
    </div>
  );
}
