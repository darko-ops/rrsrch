/**
 * The collection picker: a button naming the current collection and where it sits in the tree; it opens a search
 * box over every collection, grouped by topic path ("Medicine › Musculoskeletal › Knee osteoarthritis"). Type to
 * narrow, ↑/↓ to move, Enter to pick, Esc to close. Collections are repositories in the API.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';
import { useTopics, pathText } from './topicTree';

const fonts = {
  main: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
  mono: '"JetBrains Mono", monospace',
};
const GREEN = '#00ff88';

// collections grouped by their topic's path, topics in tree order; unfiled ones last
export function groupCollections(repos, tree, filter = '') {
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const order = new Map(tree.items.map((t, i) => [t.slug, i]));
  const groups = new Map();
  for (const r of repos || []) {
    const where = r.topic_slug && tree.bySlug.has(r.topic_slug) ? pathText(tree, r.topic_slug) : 'Not filed under a topic';
    const hay = `${r.slug} ${r.topic || ''} ${where}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) continue;
    const k = r.topic_slug && tree.bySlug.has(r.topic_slug) ? r.topic_slug : '';
    if (!groups.has(k)) groups.set(k, { slug: k, where, items: [] });
    groups.get(k).items.push(r);
  }
  return [...groups.values()].sort((a, b) => (a.slug ? order.get(a.slug) : 1e9) - (b.slug ? order.get(b.slug) : 1e9));
}

export default function CollectionPicker({ repos, repo, onRepo }) {
  const [{ tree }] = useTopics();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [at, setAt] = useState(0);
  const box = useRef(null);
  const groups = useMemo(() => groupCollections(repos, tree, text), [repos, tree, text]);
  const flat = groups.flatMap((g) => g.items);
  const current = (repos || []).find((r) => r.slug === repo);
  const where = current?.topic_slug && tree.bySlug.get(current.topic_slug)?.title;

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  useEffect(() => { setAt(0); }, [text, open]);

  const pick = (slug) => { onRepo(slug); setOpen(false); setText(''); };
  const onKey = (e) => {
    if (e.key === 'Escape') { setOpen(false); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setAt((i) => Math.min(i + 1, flat.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setAt((i) => Math.max(i - 1, 0)); }
    if (e.key === 'Enter' && flat[at]) { e.preventDefault(); pick(flat[at].slug); }
  };

  return (
    <div ref={box} style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}
        aria-label={`Collection: ${repo || 'none'}`}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 10, border: '1px solid #333', borderRadius: 8,
          padding: '6px 10px 6px 12px', background: open ? 'rgba(255,255,255,0.05)' : 'transparent', cursor: 'pointer',
          color: '#ddd', textAlign: 'left', maxWidth: 360 }}>
        <span style={{ display: 'grid', minWidth: 0 }}>
          {where && <span style={{ fontSize: 10.5, color: '#888', fontFamily: fonts.main, whiteSpace: 'nowrap',
            overflow: 'hidden', textOverflow: 'ellipsis' }}>{where}</span>}
          <span style={{ fontFamily: fonts.mono, fontSize: 12.5, whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis' }}>{repo || 'Choose a collection'}</span>
        </span>
        <ChevronDown size={14} color="#888" style={{ flexShrink: 0 }} />
      </button>
      {open && (
        <div role="dialog" aria-label="Choose a collection" style={{ position: 'absolute', right: 0, top: 'calc(100% + 6px)',
          zIndex: 50, width: 'min(420px, calc(100vw - 32px))', background: '#0c0c0c', border: '1px solid #333',
          borderRadius: 12, boxShadow: '0 16px 40px rgba(0,0,0,0.6)', overflow: 'hidden', fontFamily: fonts.main }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: '1px solid #222' }}>
            <Search size={14} color="#777" />
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
              aria-label="Find a collection" placeholder="Find a collection or topic"
              style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: '#fff', fontSize: 14 }} />
          </label>
          <div role="listbox" aria-label="Collections" style={{ maxHeight: 340, overflowY: 'auto', padding: '6px 0' }}>
            {groups.length === 0 && <div style={{ padding: '10px 14px', fontSize: 13, color: '#777' }}>No collection matches.</div>}
            {groups.map((g) => (
              <div key={g.slug || 'unfiled'}>
                <div style={{ padding: '8px 14px 4px', fontSize: 11, color: '#777' }}>{g.where}</div>
                {g.items.map((r) => {
                  const i = flat.indexOf(r);
                  const on = i === at;
                  return (
                    <div key={r.slug} role="option" aria-selected={r.slug === repo} onMouseEnter={() => setAt(i)}
                      onMouseDown={(e) => { e.preventDefault(); pick(r.slug); }}
                      style={{ padding: '7px 14px', cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'baseline',
                        background: on ? 'rgba(255,255,255,0.06)' : 'transparent',
                        boxShadow: r.slug === repo ? `inset 2px 0 0 ${GREEN}` : 'none' }}>
                      <span style={{ fontFamily: fonts.mono, fontSize: 12.5, color: '#fff', whiteSpace: 'nowrap' }}>{r.slug}</span>
                      <span style={{ fontSize: 12, color: '#888', overflow: 'hidden', textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>{r.topic}</span>
                      {r.claims != null && <span style={{ fontFamily: fonts.mono, fontSize: 11, color: '#666' }}>{r.claims}</span>}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          <a href="#/topics" onClick={() => setOpen(false)} style={{ display: 'block', padding: '10px 14px',
            borderTop: '1px solid #222', fontSize: 12.5, color: GREEN, textDecoration: 'none' }}>
            Browse every topic and collection →</a>
        </div>
      )}
    </div>
  );
}
