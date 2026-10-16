/**
 * The line under a cited passage: what it cites and where that came from (docs/SOURCES.md). A fetched or registry
 * source links to where it was fetched from; a paper links to PubMed; an upload is marked agent-supplied, with the
 * agent's account of its origin, because nobody else can fetch it to check.
 */
import React from 'react';

const short = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || '');
const AMBER = '#fab219';

export function sourceHref(ev) {
  if (ev.source_url) return ev.source_url;
  const id = String(ev.source_id || '');
  if (id.startsWith('MED:')) return `https://pubmed.ncbi.nlm.nih.gov/${id.slice(4)}/`;
  if (id.startsWith('PMC:')) return `https://www.ncbi.nlm.nih.gov/pmc/articles/${id.slice(4)}/`;
  return null;
}

export default function SourceLine({ ev, prefix, mono }) {
  const href = sourceHref(ev);
  const uploaded = ev.source_provenance === 'uploaded';
  const label = `${short(ev.source_title || '', 80)} (${ev.source_id})`;
  return (
    <div style={{ marginTop: 4, fontSize: 11, color: '#777', fontFamily: mono, display: 'flex', gap: 6, flexWrap: 'wrap',
      alignItems: 'baseline' }}>
      {prefix && <span>{prefix} ·</span>}
      {href
        ? <a href={href} target="_blank" rel="noopener noreferrer nofollow" style={{ color: '#9ab' }}>{label}</a>
        : <span>{label}</span>}
      {uploaded && (
        <span title={ev.source_origin ? `Origin, as the agent described it: ${ev.source_origin}` : undefined}
          style={{ color: AMBER, border: `1px solid ${AMBER}55`, borderRadius: 999, padding: '0 6px' }}>
          agent-supplied</span>
      )}
      {uploaded && ev.source_origin && <span style={{ color: '#666' }}>{short(ev.source_origin, 120)}</span>}
    </div>
  );
}
