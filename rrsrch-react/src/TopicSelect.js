/**
 * Choose topics from the tree: up to 8 for a post, or the one a collection sits under (max 1). Chosen ones show as
 * chips; a search box suggests topics with their path, so "knee" offers "Knee osteoarthritis · Medicine › Musculoskeletal".
 */
import React, { useState } from 'react';
import { X } from 'lucide-react';
import { useTopics, pathText } from './topicTree';

const MAX = 8;

export default function TopicSelect({ value, onChange, inputStyle, max = MAX, placeholder }) {
  const [{ tree, loading }] = useTopics();
  const [text, setText] = useState('');
  const [at, setAt] = useState(0);
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = words.length ? tree.items.filter((t) => !value.includes(t.slug)
    && words.every((w) => `${t.slug} ${pathText(tree, t.slug)}`.toLowerCase().includes(w))).slice(0, 8) : [];
  const add = (slug) => { if (value.length < max) onChange([...value, slug]); setText(''); setAt(0); };
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setAt((i) => Math.min(i + 1, matches.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setAt((i) => Math.max(i - 1, 0)); }
    if (e.key === 'Enter' && matches[at]) { e.preventDefault(); add(matches[at].slug); }
    if (e.key === 'Backspace' && !text && value.length) onChange(value.slice(0, -1));
  };
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {value.map((slug) => (
          <span key={slug} title={pathText(tree, slug)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
            border: '1px solid #2c4', borderColor: 'rgba(0,255,136,0.3)', borderRadius: 999, padding: '3px 6px 3px 10px',
            fontSize: 12.5, color: '#cfe' }}>
            {tree.bySlug.get(slug)?.title || slug}
            <button type="button" aria-label={`Remove ${slug}`} onClick={() => onChange(value.filter((s) => s !== slug))}
              style={{ background: 'none', border: 'none', color: '#8a9', cursor: 'pointer', padding: 0, display: 'inline-flex' }}>
              <X size={12} /></button>
          </span>
        ))}
        {value.length < max && (
          <input value={text} onChange={(e) => { setText(e.target.value); setAt(0); }} onKeyDown={onKey}
            aria-label="Add a topic" placeholder={placeholder || (value.length ? 'Add another topic' : 'Topics: type to find one in the tree')}
            style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
        )}
      </div>
      {matches.length > 0 && (
        <div role="listbox" aria-label="Topic suggestions" style={{ border: '1px solid #2a2a2a', borderRadius: 8, overflow: 'hidden' }}>
          {matches.map((t, i) => (
            <div key={t.slug} role="option" aria-selected={i === at} onMouseEnter={() => setAt(i)}
              onMouseDown={(e) => { e.preventDefault(); add(t.slug); }}
              style={{ padding: '7px 12px', cursor: 'pointer', fontSize: 13, color: '#ddd',
                background: i === at ? 'rgba(255,255,255,0.06)' : 'transparent' }}>
              {t.title} <span style={{ color: '#777', fontSize: 12 }}>· {pathText(tree, t.parent) || 'top level'}</span>
            </div>
          ))}
        </div>
      )}
      {words.length > 0 && !loading && matches.length === 0 && (
        <span style={{ fontSize: 12, color: '#777' }}>No topic matches. An organization admin can add one on its
          parent's <a href="#/topics" style={{ color: '#9ab' }}>topic page</a>.</span>
      )}
    </div>
  );
}
