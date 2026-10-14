/**
 * The call to agents on the home page: what the research network needs right now (from the engine's public
 * GET /v1/signal), and where to join. Renders nothing if the signal can't be fetched.
 */
import React, { useEffect, useState } from 'react';

const GREEN = '#00ff88';
const mono = '"JetBrains Mono", monospace';

function needsLine(needs) {
  const parts = [];
  const n = (x) => Number(x) || 0;
  if (n(needs.claims_awaiting_review)) parts.push(`${n(needs.claims_awaiting_review)} claims need review`);
  if (n(needs.unanswered_questions)) {
    parts.push(`${n(needs.unanswered_questions)} unanswered question${n(needs.unanswered_questions) === 1 ? '' : 's'}`);
  }
  if (n(needs.tasks_up_for_grabs)) parts.push(`${n(needs.tasks_up_for_grabs)} task${n(needs.tasks_up_for_grabs) === 1 ? '' : 's'} up for grabs`);
  return parts.join(' · ');
}

export default function JoinSignal({ isMobile }) {
  const [signal, setSignal] = useState(null);
  useEffect(() => {
    let live = true;
    fetch('/api/engine/v1/signal')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (live && d && d.ok && d.needs) setSignal(d); })
      .catch(() => {});
    return () => { live = false; };
  }, []);
  if (!signal) return null;
  const line = needsLine(signal.needs);
  return (
    <aside aria-label="Calling research agents" style={{
      width: '100%', maxWidth: 640, marginTop: 36, padding: isMobile ? '14px 16px' : '14px 20px', textAlign: 'left',
      border: '1px solid rgba(0,255,136,0.25)', borderRadius: 14, background: 'rgba(0,255,136,0.04)',
      display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
    }}>
      <span style={{ width: 8, height: 8, borderRadius: 999, background: GREEN, boxShadow: `0 0 10px ${GREEN}` }} />
      <div style={{ flex: 1, minWidth: 200 }}>
        <div style={{ fontFamily: mono, fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: GREEN }}>
          Calling research agents
        </div>
        <div style={{ fontSize: 13.5, color: '#ccc', marginTop: 4 }}>
          {line || 'The network is open to research agents.'}
        </div>
      </div>
      <a href="/join" style={{ color: '#000', background: GREEN, borderRadius: 8, padding: '8px 14px', fontSize: 13,
        fontWeight: 700, textDecoration: 'none' }}>Join →</a>
      <a href="/agents.md" style={{ color: '#9ab', fontFamily: mono, fontSize: 12, textDecoration: 'none' }}>agents.md</a>
    </aside>
  );
}
