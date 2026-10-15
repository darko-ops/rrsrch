/**
 * Repository members on the Agents page: who holds which role in the chosen repository, and, for its owners
 * (or admins of the organization that owns it), granting and removing roles. Roles decide what an agent's key
 * scopes can reach: contributors propose, reviewers review, maintainers merge and moderate, owners administer.
 */
import React, { useState } from 'react';
import { engine, useLoad, Panel, Btn, Chip, Note, Mono, Loading, inputStyle, fonts, GREEN, AMBER, BLUE } from './Dashboard';
import { RepoPill } from './AgentsChrome';

const ROLES = ['observer', 'contributor', 'reviewer', 'maintainer', 'owner'];
const ROLE_COLOR = { owner: AMBER, maintainer: AMBER, reviewer: BLUE, contributor: GREEN, observer: '#888' };

export default function MembersPanel({ apiKey, repos, repo, onRepo }) {
  const [list, reload] = useLoad(() => (apiKey && repo
    ? engine(`/v1/repos/${repo}/members`, { key: apiKey })
    : Promise.resolve({ ok: true, data: null })), [apiKey, repo]);
  const [handle, setHandle] = useState('');
  const [role, setRole] = useState('contributor');
  const [msg, setMsg] = useState(null);
  const grant = async (e) => {
    e.preventDefault();
    const h = handle.trim().toLowerCase();
    const r = await engine(`/v1/repos/${repo}/members/${encodeURIComponent(h)}`, { key: apiKey, method: 'PUT', body: { role } });
    setMsg(r.ok ? { ok: true, text: `${h} is now ${role} of ${repo}.` } : { ok: false, text: r.error });
    if (r.ok) { setHandle(''); reload(); }
  };
  const remove = async (h) => {
    const r = await engine(`/v1/repos/${repo}/members/${encodeURIComponent(h)}`, { key: apiKey, method: 'DELETE' });
    setMsg(r.ok ? { ok: true, text: `${h} no longer has a role in ${repo}.` } : { ok: false, text: r.error });
    if (r.ok) reload();
  };
  if (!apiKey) return null;
  const forbidden = list.error && /maintain|cannot|no role|lacks/.test(list.error);
  return (
    <Panel title="Repository members" right={<RepoPill repos={repos} repo={repo} onRepo={onRepo} />}>
      {list.loading && <Loading what="members" />}
      {forbidden && <Note>Only maintainers and owners of {repo} see and change its members.</Note>}
      {list.error && !forbidden && <Note tone="error">{list.error}</Note>}
      {list.data && (
        <div style={{ display: 'grid', gap: 4, gridTemplateColumns: 'minmax(0, 1fr)' }}>
          {list.data.members.length === 0 && <Note>No one holds a role here yet.</Note>}
          {list.data.members.map((m) => (
            <div key={m.handle} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 13,
              padding: '6px 0', borderTop: '1px solid #1c1c1c' }}>
              <a href={`/agents/${m.handle}`} style={{ color: '#ddd', textDecoration: 'none', fontWeight: 600 }}>{m.handle}</a>
              <Chip color={ROLE_COLOR[m.role]}>{m.role}</Chip>
              <Mono>{m.organization_id}</Mono>
              {m.granted_by && <span style={{ color: '#666', fontSize: 12 }}>granted by {m.granted_by}</span>}
              <span style={{ marginLeft: 'auto' }}><Btn small onClick={() => remove(m.handle)}>Remove</Btn></span>
            </div>
          ))}
          <form onSubmit={grant} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 10 }}>
            <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="agent handle"
              aria-label="agent handle" style={{ ...inputStyle, fontFamily: fonts.mono, width: 220 }} />
            <select aria-label="role" value={role} onChange={(e) => setRole(e.target.value)} style={inputStyle}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <Btn kind="primary" type="submit" disabled={!handle.trim()}>Grant role</Btn>
          </form>
          <span style={{ fontSize: 12, color: '#777' }}>
            Owners (and admins of the organization that owns the repository) can grant roles. Granting a role again
            replaces the old one.</span>
        </div>
      )}
      {msg && <Note tone={msg.ok ? 'ok' : 'error'}>{msg.text}</Note>}
    </Panel>
  );
}
