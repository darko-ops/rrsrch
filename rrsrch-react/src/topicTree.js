/**
 * The tree of knowledge (GET /v1/topics, docs/TOPICS.md): topics and sub-topics that collections and posts are
 * filed under. One request per page load, shared by the topic pages, the collection picker and the post composer;
 * `reloadTopics()` after adding one.
 *
 * Plain fetch, not Dashboard's engine(): the collection picker is imported by AgentsChrome, which Dashboard imports.
 */
import { useEffect, useState } from 'react';

let pending = null;
const listeners = new Set();

function get(key) {
  return fetch('/api/engine/v1/topics', { headers: key ? { Authorization: `Bearer ${key}` } : {} })
    .then((r) => r.json().catch(() => ({})).then((d) => ({ status: r.status, ok: r.ok && d.ok !== false, d })));
}

// With the visitor's key, so private collections they can read are counted; if the key is refused (expired,
// revoked, a lapsed sign-in), the public tree without it rather than an error page.
function fetchTopics() {
  let key = '';
  try { key = localStorage.getItem('rrsrch_engine_key') || localStorage.getItem('rrsrch_token') || ''; } catch { /* none */ }
  return get(key)
    .then((res) => (key && (res.status === 401 || res.status === 403) ? get('') : res))
    .then(({ ok, d }) => (ok ? d.items || [] : Promise.reject(d.error || 'request failed')));
}

export function loadTopics() {
  if (!pending) pending = fetchTopics().catch((e) => { pending = null; throw e; });
  return pending;
}

export function reloadTopics() {
  pending = null;
  return loadTopics().then((items) => { listeners.forEach((f) => f(items)); return items; });
}

/** The whole tree, as an index: by slug, children by parent (null for the top), and each topic's path from the top. */
export function indexTopics(items) {
  const bySlug = new Map((items || []).map((t) => [t.slug, t]));
  const children = new Map();
  for (const t of items || []) {
    const k = t.parent || null;
    if (!children.has(k)) children.set(k, []);
    children.get(k).push(t);
  }
  const path = (slug) => {
    const out = [];
    for (let t = bySlug.get(slug), n = 0; t && n < 12; t = bySlug.get(t.parent), n += 1) out.unshift(t);
    return out;
  };
  return { items: items || [], bySlug, children: (slug) => children.get(slug || null) || [], path };
}

/** [state, reload]: state is { loading, error, tree } with `tree` from indexTopics. */
export function useTopics() {
  const [state, setState] = useState({ loading: true, error: null, tree: indexTopics([]) });
  useEffect(() => {
    let live = true;
    const set = (items) => { if (live) setState({ loading: false, error: null, tree: indexTopics(items) }); };
    listeners.add(set);
    loadTopics().then(set, (e) => { if (live) setState({ loading: false, error: String(e), tree: indexTopics([]) }); });
    return () => { live = false; listeners.delete(set); };
  }, []);
  return [state, reloadTopics];
}

export const pathText = (tree, slug) => tree.path(slug).map((t) => t.title).join(' › ');

// for tests: forget the cached tree
export function resetTopics() { pending = null; }
