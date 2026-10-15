/**
 * Evidence that is a commit (kind "git_ref"), not a passage of a document. RRSRCH's case for a security claim often
 * rests on the code ("the fix commit isn't in that release"), so the commit has to be shown and linked as clearly as a
 * quoted passage: never as a blank source.
 *
 *   git = { repo_url, commit, tag?, path?, start_line?, end_line? }   (from the engine's evidence rows)
 */
import React from 'react';

// each public forge spells its links differently
const FORGES = {
  'github.com': { commit: (r, c) => `${r}/commit/${c}`, blob: (r, c, p) => `${r}/blob/${c}/${p}`,
    lines: (a, b) => `#L${a}-L${b}`, tag: (r, t) => `${r}/tree/${encodeURIComponent(t)}` },
  'gitlab.com': { commit: (r, c) => `${r}/-/commit/${c}`, blob: (r, c, p) => `${r}/-/blob/${c}/${p}`,
    lines: (a, b) => `#L${a}-${b}`, tag: (r, t) => `${r}/-/tags/${encodeURIComponent(t)}` },
  'codeberg.org': { commit: (r, c) => `${r}/commit/${c}`, blob: (r, c, p) => `${r}/src/commit/${c}/${p}`,
    lines: (a, b) => `#L${a}-L${b}`, tag: (r, t) => `${r}/src/tag/${encodeURIComponent(t)}` },
};

export function commitLinks(git) {
  if (!git || !/^https:\/\/[^/]+\/[^/]+\/[^/]+$/.test(git.repo_url || '') || !/^[0-9a-f]{40}$/.test(git.commit || '')) return null;
  const host = new URL(git.repo_url).host;
  const f = FORGES[host];
  if (!f) return null;
  const repo = git.repo_url.replace(/^https:\/\//, '');
  const path = git.path ? git.path.split('/').map(encodeURIComponent).join('/') : null;
  return {
    repo,
    commit: f.commit(git.repo_url, git.commit),
    file: path ? f.blob(git.repo_url, git.commit, path) + (git.start_line ? f.lines(git.start_line, git.end_line) : '') : null,
    tag: git.tag ? f.tag(git.repo_url, git.tag) : null,
  };
}

export const isCommit = (ev) => ev && ev.kind === 'git_ref' && ev.git;

export default function CommitEvidence({ ev, borderColor = '#555', mono, fontSize = 13 }) {
  const g = ev.git;
  const l = commitLinks(g);
  const link = { color: '#9ab' };
  return (
    <div style={{ borderLeft: `3px solid ${borderColor}`, padding: '6px 12px', color: '#ccc', fontSize, lineHeight: 1.6 }}>
      <div>
        <span style={{ color: '#888' }}>Commit </span>
        {l ? <a href={l.commit} target="_blank" rel="noreferrer" style={{ ...link, fontFamily: mono }}>{g.commit.slice(0, 12)}</a>
          : <span style={{ fontFamily: mono }}>{String(g.commit || '').slice(0, 12)}</span>}
        <span style={{ color: '#888' }}> in </span><span style={{ fontFamily: mono }}>{l ? l.repo : g.repo_url}</span>
      </div>
      {g.path && (
        <div>
          <span style={{ color: '#888' }}>Code: </span>
          {l && l.file ? <a href={l.file} target="_blank" rel="noreferrer" style={{ ...link, fontFamily: mono }}>
            {g.path}{g.start_line ? ` lines ${g.start_line}–${g.end_line}` : ''}</a>
            : <span style={{ fontFamily: mono }}>{g.path}</span>}
          <span style={{ color: '#888' }}> at this commit</span>
        </div>
      )}
      {g.tag && (
        <div>
          <span style={{ color: '#888' }}>Release tag it should be in: </span>
          {l && l.tag ? <a href={l.tag} target="_blank" rel="noreferrer" style={{ ...link, fontFamily: mono }}>{g.tag}</a>
            : <span style={{ fontFamily: mono }}>{g.tag}</span>}
        </div>
      )}
      <div style={{ marginTop: 4, fontSize: 11, color: '#777', fontFamily: mono }}>{ev.relation} · commit evidence</div>
    </div>
  );
}

// A proposed piece of evidence in a merge request: [relation, span-or-commit]. A reviewer approving a commit must see
// which commit it is.
export function ProposedEvidence({ rel, ev, Mono }) {
  if (ev && ev.commit && ev.repo_url) {
    const l = commitLinks(ev);
    const text = `${l ? l.repo : ev.repo_url}@${String(ev.commit).slice(0, 12)}${ev.path ? `:${ev.path}` : ''}${
      ev.start_line ? `#L${ev.start_line}-${ev.end_line}` : ''}${ev.tag ? ` (in ${ev.tag}?)` : ''}`;
    return <Mono>{rel} · commit {l ? <a href={l.file || l.commit} target="_blank" rel="noreferrer" style={{ color: '#9ab' }}>{text}</a> : text}</Mono>;
  }
  return <Mono>{rel} · {ev.source_id} [{ev.start}–{ev.end}]</Mono>;
}
