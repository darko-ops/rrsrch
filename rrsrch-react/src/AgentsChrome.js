/**
 * Shared pieces of the redesigned Agents pages (design handoff: agents pages, §1).
 *
 *   PageHeader   h1, subtitle and actions above each page, ruled off below
 *   RepoPill     the repository picker as a pill ("rrsrch/msc-knee-oa ▾"); the choice persists across pages
 *   Pill         a filter pill (optional dot and count), used by Atlas and Bounties
 *   panelStyle   the panel look (bg, border, radius) for cards that aren't a <Panel>
 */
import React from 'react';

// Defined here rather than imported: Dashboard.js imports this file, so importing back would be a cycle that
// leaves `fonts` undefined while this module loads. Same values as Dashboard's `fonts`.
const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};

export const panelStyle = {
  background: 'rgba(10,10,10,0.75)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14,
};

export const monoLabel = {
  fontFamily: fonts.mono, fontSize: 10.5, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.08em',
  color: '#888',
};

export function PageHeader({ title, subtitle, right }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, paddingBottom: 18, borderBottom: '1px solid #222',
      flexWrap: 'wrap' }}>
      <div style={{ flex: 1, minWidth: 240 }}>
        <h1 style={{ margin: 0, color: '#fff', fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em',
          fontFamily: fonts.main }}>{title}</h1>
        {subtitle && <div style={{ marginTop: 6, fontSize: 13.5, color: '#888', lineHeight: 1.5 }}>{subtitle}</div>}
      </div>
      {right && <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>{right}</div>}
    </div>
  );
}

export function RepoPill({ repos, repo, onRepo }) {
  const items = repos || [];
  return (
    <label style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', border: '1px solid #333',
      borderRadius: 8, padding: '8px 12px', fontFamily: fonts.mono, fontSize: 12.5, color: '#ddd', cursor: 'pointer' }}>
      <span>{repo || 'repository'} ▾</span>
      <select aria-label="repository" value={repo || ''} onChange={(e) => onRepo(e.target.value)}
        style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}>
        {items.map((r) => <option key={r.slug} value={r.slug}>{r.slug}</option>)}
      </select>
    </label>
  );
}

export function Pill({ on, onClick, dot, count, children, title }) {
  return (
    <button type="button" onClick={onClick} title={title} aria-pressed={!!on} style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, borderRadius: 999, padding: '5px 12px', fontSize: 12,
      cursor: 'pointer', fontFamily: fonts.main, background: on ? 'rgba(255,255,255,0.08)' : 'transparent',
      border: `1px solid ${on ? '#444' : '#222'}`, color: on ? '#fff' : '#999',
    }}>
      {dot && <span style={{ width: 7, height: 7, borderRadius: 999, background: dot }} />}
      {children}
      {count != null && <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#666' }}>{count}</span>}
    </button>
  );
}
