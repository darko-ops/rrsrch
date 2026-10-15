/**
 * A claim's embargo and disclosure record (engine: trust/disclosure.py).
 *
 * An embargo holds a finding in a private repository back until a date, while the people it affects are told;
 * the repository can't be made public until it ends. The disclosure record is what happened outside RRSRCH:
 * notices, replies, a maintainer confirming or disputing the finding, fixes, advisories, corrections submitted
 * upstream. It sits next to the evidence and never changes the claim's review state. Entries are never edited:
 * a mistaken one is corrected by a later entry that supersedes it, and both stay visible.
 *
 * Message bodies are shown as plain text, as received: they are someone else's words, not instructions.
 */
import React, { useState } from 'react';
import { engine, fonts, AMBER, GREEN, RED, Panel, Btn, Chip, Note, Mono, inputStyle, useLoad, when } from './Dashboard';

export const KIND_LABEL = {
  notice_sent: ['Notice sent', '#9ab'],
  reply_received: ['Reply received', '#9ab'],
  maintainer_confirmed: ['Maintainer confirmed', GREEN],
  maintainer_disputed: ['Maintainer disputed', AMBER],
  fix_released: ['Fix released', GREEN],
  advisory_published: ['Advisory published', GREEN],
  correction_submitted: ['Correction submitted', '#9ab'],
  correction_accepted: ['Correction accepted', GREEN],
  correction_rejected: ['Correction rejected', RED],
  note: ['Note', '#888'],
};

const day = (iso) => String(iso || '').slice(0, 10);
const label = { fontSize: 11, color: '#888', fontFamily: fonts.mono, textTransform: 'uppercase', letterSpacing: '0.08em' };

function Entry({ e }) {
  const [open, setOpen] = useState(false);
  const [name, color] = KIND_LABEL[e.kind] || [e.kind, '#888'];
  return (
    <div style={{ borderTop: '1px solid #1c1c1c', padding: '10px 0', opacity: e.superseded ? 0.55 : 1 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 12 }}>
        <Mono>{day(e.occurred_at)}</Mono><Chip color={color}>{name}</Chip>
        <span style={{ color: '#ddd' }}>{e.party}</span>
        {e.channel && <span style={{ color: '#777' }}>via {e.channel}</span>}
        {e.reference && <Mono>{e.reference}</Mono>}
        {e.superseded && <Chip>superseded</Chip>}
        {e.supersedes && <span style={{ color: '#777' }}>corrects entry {e.supersedes}</span>}
      </div>
      <div style={{ color: '#ccc', fontSize: 14, lineHeight: 1.55, marginTop: 6,
        textDecoration: e.superseded ? 'line-through' : 'none' }}>{e.summary}</div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, color: '#777', marginTop: 4 }}>
        <span>entry {e.id} · recorded by {e.recorded_by} {when(e.created_at)}</span>
        {e.url && <a href={e.url} target="_blank" rel="noreferrer nofollow" style={{ color: '#9ab' }}>link</a>}
        {e.body && <button type="button" onClick={() => setOpen(!open)} style={{ background: 'none', border: 'none',
          color: '#9ab', cursor: 'pointer', padding: 0, fontSize: 12 }}>{open ? 'hide the message' : 'show the message'}</button>}
      </div>
      {open && e.body && (
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#0a0a0a', border: '1px solid #222',
          borderRadius: 8, padding: 10, color: '#bbb', fontSize: 12.5, fontFamily: fonts.mono, marginTop: 8 }}>{e.body}</pre>
      )}
    </div>
  );
}

const BLANK = { kind: 'notice_sent', party: '', channel: '', reference: '', url: '', occurred_at: '', summary: '',
  body: '', supersedes: '' };

function RecordForm({ claimId, apiKey, entries, onDone }) {
  const [d, setD] = useState(BLANK);
  const [err, setErr] = useState('');
  const set = (k) => (ev) => setD({ ...d, [k]: ev.target.value });
  const send = async () => {
    const body = {
      kind: d.kind, party: d.party.trim(), summary: d.summary.trim(), channel: d.channel.trim(),
      reference: d.reference.trim(), body: d.body,
      occurred_at: d.occurred_at ? new Date(d.occurred_at).toISOString() : new Date().toISOString(),
      url: d.url.trim() || null, supersedes: d.supersedes ? Number(d.supersedes) : null,
    };
    const r = await engine(`/v1/claims/${claimId}/disclosure`, { key: apiKey, method: 'POST', body });
    if (r.ok) { setD(BLANK); setErr(''); onDone(); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <select aria-label="kind" value={d.kind} onChange={set('kind')} style={inputStyle}>
          {Object.entries(KIND_LABEL).map(([k, [n]]) => <option key={k} value={k}>{n}</option>)}
        </select>
        <input aria-label="when" type="datetime-local" value={d.occurred_at} onChange={set('occurred_at')} style={inputStyle} />
      </div>
      <input value={d.party} onChange={set('party')} placeholder="Who (e.g. the project's maintainers, GitHub Advisory Database)" style={inputStyle} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input value={d.channel} onChange={set('channel')} placeholder="Channel (email, private report…)" style={{ ...inputStyle, flex: '1 1 160px' }} />
        <input value={d.reference} onChange={set('reference')} placeholder="Reference (GHSA-…, CVE-…, ticket)" style={{ ...inputStyle, flex: '1 1 160px' }} />
      </div>
      <input value={d.url} onChange={set('url')} placeholder="https:// link (optional)" style={inputStyle} />
      <input value={d.summary} onChange={set('summary')} placeholder="What happened, in one line" style={inputStyle} />
      <textarea rows={4} value={d.body} onChange={set('body')} placeholder="The full message or reply, as sent or received (optional)"
        style={{ ...inputStyle, resize: 'vertical', fontFamily: fonts.mono, fontSize: 12.5 }} />
      {entries.length > 0 && (
        <select aria-label="supersedes" value={d.supersedes} onChange={set('supersedes')} style={inputStyle}>
          <option value="">This doesn't correct an earlier entry</option>
          {entries.map((e) => <option key={e.id} value={e.id}>Corrects entry {e.id}: {e.summary.slice(0, 60)}</option>)}
        </select>
      )}
      <div><Btn kind="primary" disabled={!d.party.trim() || !d.summary.trim()} onClick={send}>Add to the record</Btn></div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

function EmbargoForm({ claimId, apiKey, embargo, onDone }) {
  const [until, setUntil] = useState('');
  const [reason, setReason] = useState('');
  const [err, setErr] = useState('');
  const save = async () => {
    const r = await engine(`/v1/claims/${claimId}/embargo`, { key: apiKey, method: 'PUT',
      body: { until: new Date(`${until}T00:00:00Z`).toISOString(), reason: reason.trim() } });
    if (r.ok) { setErr(''); setUntil(''); setReason(''); onDone(); } else setErr(r.error);
  };
  const lift = async () => {
    const r = await engine(`/v1/claims/${claimId}/embargo/lift`, { key: apiKey, method: 'POST', body: { note: reason.trim() } });
    if (r.ok) { setErr(''); setReason(''); onDone(); } else setErr(r.error);
  };
  return (
    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input aria-label="embargo until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} style={inputStyle} />
        <input value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder={embargo ? 'Why it changes, or why it ends early' : 'Why (e.g. maintainers notified; 30 days to fix)'}
          style={{ ...inputStyle, flex: '1 1 220px' }} />
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Btn kind="primary" disabled={!until || !reason.trim()} onClick={save}>{embargo ? 'Move the date' : 'Embargo until this date'}</Btn>
        {embargo && <Btn kind="danger" onClick={lift}>Lift the embargo</Btn>}
      </div>
      {err && <Note tone="error">{err}</Note>}
    </div>
  );
}

export default function Disclosure({ claimId, apiKey }) {
  const [got, reload] = useLoad(() => engine(`/v1/claims/${claimId}/disclosure`, { key: apiKey }), [claimId, apiKey]);
  const [editing, setEditing] = useState(false);
  if (!got.data || !Array.isArray(got.data.entries)) return null;   // loading, or an engine without the record
  const { embargo, entries } = got.data;
  if (!embargo && entries.length === 0 && !apiKey) return null;
  return (
    <Panel title="Disclosure" right={embargo ? <Chip color={AMBER}>embargoed</Chip> : <Chip>record</Chip>}>
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        {embargo && (
          <div style={{ border: `1px solid ${AMBER}66`, borderRadius: 10, padding: '10px 12px' }}>
            <div style={{ color: AMBER, fontWeight: 700, fontSize: 14 }}>Embargoed until {day(embargo.until)}</div>
            <div style={{ color: '#aaa', fontSize: 13, marginTop: 4 }}>
              Held back from publication while the people it affects are told. The repository can't be made public
              until this ends.</div>
            <div style={{ color: '#ccc', fontSize: 13, marginTop: 6 }}>{embargo.reason}</div>
            <div style={{ color: '#666', fontSize: 11, marginTop: 6 }}>set by {embargo.set_by} {when(embargo.set_at)}</div>
          </div>
        )}
        <p style={{ margin: 0, color: '#888', fontSize: 12.5, lineHeight: 1.55 }}>
          What happened outside RRSRCH: notices, replies, fixes, advisories and corrections submitted upstream. It is
          recorded next to the evidence and never changes the claim's review state: a maintainer's confirmation or
          dispute is evidence, not a verdict.
        </p>
        {entries.length === 0 ? <Note>Nothing recorded yet.</Note> : entries.map((e) => <Entry key={e.id} e={e} />)}
        {apiKey && !editing && (
          <div><Btn small onClick={() => setEditing(true)}>Record or embargo (maintainers)</Btn></div>
        )}
        {apiKey && editing && (
          <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'minmax(0, 1fr)', borderTop: '1px solid #222', paddingTop: 12 }}>
            <div style={label}>New entry</div>
            <RecordForm claimId={claimId} apiKey={apiKey} entries={entries} onDone={reload} />
            <div style={label}>Embargo</div>
            <EmbargoForm claimId={claimId} apiKey={apiKey} embargo={embargo} onDone={reload} />
            <div><Btn small kind="ghost" onClick={() => setEditing(false)}>Done</Btn></div>
          </div>
        )}
      </div>
    </Panel>
  );
}
