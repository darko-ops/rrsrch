/**
 * The tree of knowledge (docs/TOPICS.md): every topic and collection on RRSRCH, at #/topics, and one topic at
 * /topics/<slug>.
 *
 *   TreeNav      the whole tree on the left: expand and collapse, filter by name, counts of what's under each
 *   TopicIndex   #/topics: the top-level topics with their sub-topics
 *   TopicView    /topics/<slug>: the path to it, its research missions (Missions.js), its sub-topics and collections,
 *                then the questions and findings
 *                filed anywhere under it. Anyone signed in can add a sub-topic here, or a topic on the index.
 *
 * Collections are repositories in the API.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import { engine, actingKey, fonts, GREEN, Btn, Note, Loading, inputStyle, useLoad } from './Dashboard';
import { panelStyle, monoLabel } from './AgentsChrome';
import { ExplorePage, useFollows } from './Research';
import { useTopics, reloadTopics } from './topicTree';
import { goTo } from './routes';
import { TopicMissions } from './Missions';

const panel = { ...panelStyle, padding: '18px 20px', display: 'grid', gap: 10, alignContent: 'start', minWidth: 0 };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const totals = (t) => [t.collections && plural(t.collections, 'collection'), t.claims && plural(t.claims, 'claim'),
  t.posts && plural(t.posts, 'post')].filter(Boolean).join(' · ') || 'nothing filed yet';

function TopicLink({ slug, children, style }) {
  return (
    <a href={`/topics/${slug}`} onClick={(e) => { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); goTo(`/topics/${slug}`); } }}
      style={{ textDecoration: 'none', ...style }}>{children}</a>
  );
}

// -- the tree on the left -------------------------------------------------------------------------------------------

function TreeNav({ tree, current }) {
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState(() => new Set(tree.path(current).map((t) => t.slug)));
  useEffect(() => { setOpen((o) => new Set([...o, ...tree.path(current).map((t) => t.slug)])); }, [current, tree]);
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  // filtering: the matches, everything above them, all open
  const shown = useMemo(() => {
    if (!words.length) return null;
    const keep = new Set();
    for (const t of tree.items) {
      if (words.every((w) => `${t.title} ${t.slug} ${t.description}`.toLowerCase().includes(w))) {
        tree.path(t.slug).forEach((x) => keep.add(x.slug));
      }
    }
    return keep;
  }, [tree, words.join(' ')]);   // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (slug) => setOpen((o) => { const n = new Set(o); if (n.has(slug)) n.delete(slug); else n.add(slug); return n; });

  const rows = (parent, depth) => tree.children(parent).filter((t) => !shown || shown.has(t.slug)).map((t) => {
    const kids = tree.children(t.slug).length > 0;
    const isOpen = shown ? true : open.has(t.slug);
    const on = t.slug === current;
    return (
      <li key={t.slug} role="treeitem" aria-expanded={kids ? isOpen : undefined} aria-selected={on}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, paddingLeft: depth * 14, borderRadius: 6,
          background: on ? 'rgba(0,255,136,0.08)' : 'transparent' }}>
          {kids
            ? <button type="button" aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${t.title}`} onClick={() => toggle(t.slug)}
                style={{ background: 'none', border: 'none', padding: 2, cursor: 'pointer', color: '#888', display: 'inline-flex' }}>
                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>
            : <span style={{ width: 18 }} />}
          <TopicLink slug={t.slug} style={{ flex: 1, minWidth: 0, padding: '6px 4px', fontSize: 13.5,
            color: on ? '#fff' : '#ccc', fontWeight: on ? 600 : 400, whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis' }}>{t.title}</TopicLink>
          {t.total.claims + t.total.posts > 0 && (
            <span title={totals(t.total)} style={{ fontFamily: fonts.mono, fontSize: 10.5, color: '#666', paddingRight: 6 }}>
              {t.total.claims + t.total.posts}</span>
          )}
        </div>
        {kids && isOpen && <ul role="group" style={{ listStyle: 'none', margin: 0, padding: 0 }}>{rows(t.slug, depth + 1)}</ul>}
      </li>
    );
  });

  return (
    <nav aria-label="Topic tree" style={{ ...panel, gap: 8, padding: '14px 10px' }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1px solid #2a2a2a', borderRadius: 8,
        padding: '0 10px', margin: '0 4px 4px' }}>
        <Search size={13} color="#777" />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter topics"
          placeholder="Filter topics" style={{ flex: 1, minWidth: 0, background: 'transparent', border: 'none',
            outline: 'none', color: '#fff', fontSize: 13, padding: '8px 0', fontFamily: fonts.main }} />
      </label>
      <a href="#/topics" style={{ ...monoLabel, padding: '2px 8px', textDecoration: 'none',
        color: current ? '#888' : GREEN }}>All topics</a>
      <ul role="tree" aria-label="Topics" style={{ listStyle: 'none', margin: 0, padding: 0 }}>{rows(null, 0)}</ul>
      {shown && shown.size === 0 && <span style={{ fontSize: 12.5, color: '#777', padding: '4px 8px' }}>No topic matches.</span>}
    </nav>
  );
}

// -- a topic's sub-topics, as cards ---------------------------------------------------------------------------------

function TopicCards({ items, tree }) {
  if (!items.length) return null;
  return (
    <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 230px), 1fr))' }}>
      {items.map((t) => (
        <TopicLink key={t.slug} slug={t.slug} style={{ ...panel, gap: 6, color: 'inherit' }}>
          <span style={{ color: '#fff', fontSize: 15, fontWeight: 600 }}>{t.title}</span>
          {t.description && <span style={{ color: '#999', fontSize: 12.5, lineHeight: 1.5 }}>{t.description}</span>}
          <span style={{ fontSize: 12, color: '#777' }}>{totals(t.total)}</span>
          {tree && tree.children(t.slug).length > 0 && (
            <span style={{ fontSize: 12, color: '#8fd9b6', lineHeight: 1.6 }}>
              {tree.children(t.slug).map((c) => c.title).join(' · ')}</span>
          )}
        </TopicLink>
      ))}
    </div>
  );
}

function TopicIndex({ tree, isMobile }) {
  const apiKey = actingKey();
  return (
    <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
      <header style={{ display: 'grid', gap: 6, paddingBottom: 16, borderBottom: '1px solid #222' }}>
        <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 22 : 26, fontWeight: 700, letterSpacing: '-0.02em' }}>Topics</h1>
        <span style={{ fontSize: 13.5, color: '#888', lineHeight: 1.5 }}>Everything on RRSRCH, by topic. Each topic holds
          sub-topics, collections of reviewed claims, and the questions and findings filed under it.</span>
      </header>
      <TopicCards items={tree.children(null)} tree={tree} />
      {apiKey && <AddTopic parent={null} apiKey={apiKey} />}
    </div>
  );
}

// -- adding a topic or sub-topic (anyone signed in) ----------------------------------------------------------------

function AddTopic({ parent, apiKey }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  if (!open) return <div><Btn small onClick={() => setOpen(true)}>{parent ? 'Add a sub-topic' : 'Add a topic'}</Btn></div>;
  const send = async () => {
    setBusy(true); setErr('');
    const r = await engine('/v1/topics', { key: apiKey, method: 'POST',
      body: { title: title.trim(), parent: parent ? parent.slug : null, description: description.trim() } });
    setBusy(false);
    if (!r.ok) { setErr(r.error); return; }
    await reloadTopics();
    goTo(`/topics/${r.data.topic.slug}`);
  };
  return (
    <section aria-label={parent ? 'Add a sub-topic' : 'Add a topic'} style={{ ...panel, gap: 8 }}>
      <span style={monoLabel}>{parent ? `New sub-topic under ${parent.title}` : 'New top-level topic'}</span>
      <input aria-label="Topic title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={80}
        placeholder={parent ? 'e.g. Hip osteoarthritis' : 'e.g. Biology'} style={inputStyle} />
      <input aria-label="Topic description" value={description} onChange={(e) => setDescription(e.target.value)}
        maxLength={500} placeholder="What it covers, in a line (optional)" style={inputStyle} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Btn small kind="primary" disabled={busy || !title.trim()} onClick={send}>Add it</Btn>
        <Btn small onClick={() => setOpen(false)}>Cancel</Btn>
        <span style={{ fontSize: 11.5, color: '#666' }}>Anyone can see it; check the tree for one that fits first.
          RRSRCH may rename or move it to keep the tree tidy.</span>
      </div>
      {err && <Note tone="error">{err}</Note>}
    </section>
  );
}

// -- one topic --------------------------------------------------------------------------------------------------------

function TopicView({ slug, tree, isMobile }) {
  const apiKey = actingKey();
  const path = `/v1/topics/${encodeURIComponent(slug)}`;
  // a refused key (expired, revoked) still gets the public page
  const [got] = useLoad(() => engine(path, { key: apiKey }).then((r) => (apiKey && [401, 403].includes(r.status)
    ? engine(path) : r)), [slug, apiKey]);
  const follows = useFollows(apiKey);
  if (got.loading && !got.data) return <Loading what="the topic" />;
  if (got.error) return <Note tone="error">{got.error === 'not found' ? `No topic ${slug}.` : got.error}</Note>;
  const t = got.data.topic;
  const following = follows.following(`topic:${slug}`);
  const children = t.children.map((c) => tree.bySlug.get(c.slug) || c);

  return (
    <div style={{ display: 'grid', gap: 20, minWidth: 0 }}>
      <header style={{ display: 'grid', gap: 8, paddingBottom: 16, borderBottom: '1px solid #222' }}>
        <nav aria-label="Topic path" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 12.5, color: '#777' }}>
          <a href="#/topics" style={{ color: '#888', textDecoration: 'none' }}>Topics</a>
          {t.path.slice(0, -1).map((x) => (
            <React.Fragment key={x.slug}><span>›</span><TopicLink slug={x.slug} style={{ color: '#888' }}>{x.title}</TopicLink></React.Fragment>
          ))}
        </nav>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <h1 style={{ margin: 0, color: '#fff', fontSize: isMobile ? 22 : 28, fontWeight: 700, letterSpacing: '-0.02em',
            flex: 1, minWidth: 200 }}>{t.title}</h1>
          {apiKey && <Btn small kind={following ? 'ghost' : 'primary'} onClick={() => follows.toggle(`topic:${slug}`)}
            title="Questions and findings filed here or anywhere under it reach you at check-in and in your inbox">
            {following ? 'Following' : 'Follow'}</Btn>}
        </div>
        {t.description && <span style={{ fontSize: 14, color: '#aaa', lineHeight: 1.5 }}>{t.description}</span>}
        <span style={{ fontSize: 12.5, color: '#777' }}>{totals(t.total)}, including everything under it</span>
      </header>

      <TopicMissions missions={t.missions} title={t.title} />

      {children.length > 0 && (
        <section aria-label="Sub-topics" style={{ display: 'grid', gap: 10 }}>
          <span style={monoLabel}>Sub-topics · {children.length}</span>
          <TopicCards items={children} tree={tree} />
        </section>
      )}
      {apiKey && <AddTopic parent={t} apiKey={apiKey} />}

      <section aria-label="Collections" style={{ display: 'grid', gap: 10 }}>
        <span style={monoLabel}>Collections here · {t.collections.length}</span>
        {t.collections.length === 0
          ? <span style={{ fontSize: 13, color: '#777' }}>No collection is filed directly under {t.title}
              {children.length ? '; its sub-topics may have some' : ''}.</span>
          : t.collections.map((c) => (
            <a key={c.slug} href={`#/agents?tab=tasks&repo=${encodeURIComponent(c.slug)}`}
              style={{ ...panel, gap: 4, textDecoration: 'none', color: 'inherit' }}>
              <span style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: fonts.mono, fontSize: 13, color: '#fff' }}>{c.slug}</span>
                <span style={{ fontSize: 12, color: '#777' }}>{plural(c.claims, 'claim')}{c.visibility === 'private' ? ' · private' : ''}</span>
              </span>
              <span style={{ fontSize: 14, color: '#ddd' }}>{c.title}</span>
              {c.description && <span style={{ fontSize: 12.5, color: '#999', lineHeight: 1.5 }}>{c.description}</span>}
            </a>
          ))}
      </section>

      <section aria-label="Questions and findings" style={{ display: 'grid', gap: 10 }}>
        <span style={monoLabel}>Questions and findings, here and under it</span>
        <ExplorePage key={slug} initialTopic={slug} embedded isMobile={isMobile} />
      </section>
    </div>
  );
}

export default function TopicsPage({ slug, isMobile }) {
  const [{ tree, loading, error }] = useTopics();
  if (loading && !tree.items.length) return <Loading what="topics" />;
  if (error) return <Note tone="error">{error}</Note>;
  return (
    <div style={{ display: 'grid', gap: 24, alignItems: 'start', fontFamily: fonts.main,
      gridTemplateColumns: isMobile ? 'minmax(0, 1fr)' : '260px minmax(0, 1fr)' }}>
      {isMobile
        ? <>
            <details open={!slug} style={{ ...panelStyle, padding: '10px 12px' }}>
              <summary style={{ cursor: 'pointer', fontSize: 13.5, color: '#ccc' }}>Browse the topic tree</summary>
              <div style={{ marginTop: 8 }}><TreeNav tree={tree} current={slug} /></div>
            </details>
            {slug ? <TopicView slug={slug} tree={tree} isMobile /> : <TopicIndex tree={tree} isMobile />}
          </>
        : <><div style={{ position: 'sticky', top: 0 }}><TreeNav tree={tree} current={slug} /></div>
            {slug ? <TopicView slug={slug} tree={tree} /> : <TopicIndex tree={tree} />}</>}
    </div>
  );
}
