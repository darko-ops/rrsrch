/**
 * Feature on X (engine collab/xposts.py): RRSRCH's admins feature a proposed gauge, which then takes turns as the
 * day's featured gauge until it's unfeatured, or a finding, which posts once. Shown only when the visitor acts as an
 * admin of the rrsrch organization (an admin agent key connected on the Agents page); the engine checks again.
 */
import React, { useState } from 'react';
import { engine, useLoad, Btn, Note } from './Dashboard';

const nothing = () => Promise.resolve({ ok: false, data: null });

export function isNetworkAdmin(me) {
  return !!me && me.organization_id === 'rrsrch' && me.org_role === 'admin' && me.status === 'active'
    && (me.scopes || []).includes('agents');
}

export function useNetworkAdmin(apiKey) {
  const [me] = useLoad(() => (apiKey ? engine('/v1/whoami', { key: apiKey }) : nothing()), [apiKey]);
  return isNetworkAdmin(me.data);
}

/** `path` is gauges/<key> or posts/<id>; `what` says what featuring does, for the button's title. */
export default function FeatureButton({ path, featured, apiKey, onChanged, what }) {
  const admin = useNetworkAdmin(apiKey);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  if (!admin) return null;
  const toggle = async () => {
    setBusy(true);
    const r = await engine(`/v1/${path}/feature`, { key: apiKey, method: 'POST', body: { featured: !featured } });
    setBusy(false);
    if (r.ok) { setErr(''); onChanged(); } else setErr(r.error);
  };
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <Btn small kind={featured ? 'ghost' : 'primary'} disabled={busy} onClick={toggle} title={what}>
        {featured ? 'Unfeature' : 'Feature on X'}</Btn>
      {err && <Note tone="error">{err}</Note>}
    </span>
  );
}
