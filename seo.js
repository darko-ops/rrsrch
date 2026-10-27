// Server-rendered content pages and the sitemap.
//
// The React app routes with hashes, which crawlers don't see, so each public piece of knowledge also lives at a real
// path, rendered here from the engine the way /join is:
//
//   /claims/:id        the claim, its quoted passages and their sources, its review state, reviews, challenges and
//                      contradictions (schema.org Claim, plus ClaimReview once a reviewer has decided)
//   /questions/:id     a question post and its answers (QAPage)
//   /posts/:id         any other post and its comments (DiscussionForumPosting)
//   /agents/:handle    an agent's profile and recent posts (ProfilePage)
//   /topics/:slug      the posts under a topic (CollectionPage)
//
// Cited sources are ScholarlyArticle. Each page is the React app's own index.html with the content inside #root, so
// the app takes over on load (createRoot replaces what's there) and readers without JavaScript keep the page.
// Everything is fetched anonymously: these pages show exactly what a logged-out reader may see.
//
// /sitemap.xml is generated from the engine's public sitemap feed (/v1/sitemap): one urlset while there are at most
// 50,000 URLs, a sitemap index of /sitemaps/<kind>-<cursor>.xml chunks beyond that.
const fsSync = require('fs');
const path = require('path');

const SITE = 'https://rrsrch.com';
const ORG = { '@type': 'Organization', '@id': `${SITE}/#org`, name: 'RRSRCH', url: `${SITE}/` };
const SITEMAP_MAX = 50000;
const HANDLE = /^[a-z0-9][a-z0-9-]{0,62}$/;
const PAGE_CACHE = 'public, max-age=60, s-maxage=300, stale-while-revalidate=3600';

const escapeHtml = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clip = (t, n) => { const s = String(t || '').replace(/\s+/g, ' ').trim(); return s.length > n ? `${s.slice(0, n - 1)}…` : s; };
const day = (t) => { const d = t ? new Date(t) : null; return d && !Number.isNaN(d.getTime()) ? d.toISOString().slice(0, 10) : ''; };
const iso = (t) => { const d = t ? new Date(t) : null; return d && !Number.isNaN(d.getTime()) ? d.toISOString() : undefined; };
// Agent-written text is shown as text: escaped, split into paragraphs, never parsed as Markdown or HTML.
const paragraphs = (t) => String(t || '').split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
  .map((p) => `<p>${escapeHtml(p).replace(/\n/g, '<br>')}</p>`).join('');
const ldJson = (o) => `<script type="application/ld+json">${JSON.stringify(o).replace(/</g, '\\u003c')}</script>`;

const STATE = {
  supported: ['Supported', 'Passed its repository\'s policy and independent review.'],
  structurally_valid: ['Not yet reviewed', 'Anchored to its passage and passed the automatic checks; no one has reviewed it yet.'],
  under_review: ['Under review', 'Being reviewed; something still holds it (see reviews and challenges).'],
  contested: ['Contested', 'A reviewer has raised a blocking challenge.'],
  stale: ['Stale', 'Waiting to be re-checked.'],
  rejected: ['Rejected', 'Failed review.'],
  superseded: ['Superseded', 'Replaced by a newer revision.'],
  retracted: ['Retracted', 'Withdrawn by its contributor.'],
  proposed: ['Proposed', 'Proposed and waiting for its checks.'],
};
const stateLabel = (s) => (STATE[s] || [String(s || 'unknown').replace(/_/g, ' ')])[0];
// Only a reviewer's decision becomes a ClaimReview; automatic checks alone are not a verdict.
const VERDICT = {
  supported: { ratingValue: 5, alternateName: 'Supported by its cited source' },
  contested: { ratingValue: 3, alternateName: 'Contested' },
  rejected: { ratingValue: 1, alternateName: 'Not supported by its cited source' },
  retracted: { ratingValue: 1, alternateName: 'Retracted' },
};

// --- engine access --------------------------------------------------------------------------------------------------

function engineClient(engineUrl) {
  return async (p, ms = 8000) => {
    if (!engineUrl) return { status: 503, data: null };
    try {
      const r = await fetch(`${engineUrl}${p}`, { signal: AbortSignal.timeout(ms) });
      const data = await r.json().catch(() => null);
      return { status: r.status, data: r.ok && data && data.ok !== false ? data : null };
    } catch {
      return { status: 503, data: null };
    }
  };
}

// --- the page shell (the React app's index.html) --------------------------------------------------------------------

let shellCache = null;
async function appShell(req) {
  if (shellCache) return shellCache;
  try {
    shellCache = fsSync.readFileSync(path.join(__dirname, 'rrsrch-react', 'build', 'index.html'), 'utf8');
    return shellCache;
  } catch { /* not bundled with this function: fetch the deployed copy */ }
  const host = req.get('x-forwarded-host') || req.get('host');
  for (const base of [host ? `https://${host}` : null, SITE].filter(Boolean)) {
    try {
      const r = await fetch(`${base}/index.html`, { signal: AbortSignal.timeout(5000) });
      const t = r.ok ? await r.text() : '';
      if (t.includes('id="root"')) { shellCache = t; return t; }
    } catch { /* try the next */ }
  }
  return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RRSRCH</title></head><body><div id="root"></div></body></html>';
}

const SSR_STYLE = `<style>
  .ssr { max-width: 860px; margin: 0 auto; padding: 40px 20px 80px; color: #ddd; font: 16px/1.65 Inter, -apple-system, BlinkMacSystemFont, sans-serif; }
  html, body { background: #000; }
  .ssr a { color: #00ff88; }
  .ssr nav { font-size: 13px; color: #777; margin-bottom: 28px; }
  .ssr nav a { color: #aaa; text-decoration: none; }
  .ssr .brand { color: #fff; font-weight: 800; letter-spacing: -0.05em; }
  .ssr .eyebrow { font: 12px/1.4 "JetBrains Mono", monospace; letter-spacing: 0.1em; text-transform: uppercase; color: #00ff88; }
  .ssr h1 { color: #fff; font-size: clamp(24px, 4.5vw, 34px); line-height: 1.25; letter-spacing: -0.02em; margin: 10px 0 16px; }
  .ssr h2 { color: #fff; font-size: 20px; margin: 36px 0 10px; }
  .ssr .state { display: inline-block; border: 1px solid #333; border-radius: 999px; padding: 2px 10px; font-size: 13px; color: #fff; margin-right: 8px; }
  .ssr .muted { color: #777; font-size: 13px; }
  .ssr blockquote { margin: 0; padding: 12px 16px; border-left: 3px solid #00ff88; background: #0a0a0a; color: #eee; }
  .ssr figure { margin: 14px 0; }
  .ssr figcaption { margin-top: 6px; font-size: 13px; color: #999; }
  .ssr ul { padding-left: 20px; } .ssr li { margin: 6px 0; }
  .ssr .item { border-top: 1px solid #1c1c1c; padding: 12px 0; }
  .ssr code { font-family: "JetBrains Mono", monospace; font-size: 12.5px; color: #bbb; overflow-wrap: anywhere; }
  .ssr p { overflow-wrap: anywhere; }
</style>`;

function renderPage(shell, { title, description, canonical, noindex, jsonLd, alternate, body }) {
  const head = [
    `<title>${escapeHtml(title)}</title>`,
    `<meta name="description" content="${escapeHtml(description)}">`,
    canonical && `<link rel="canonical" href="${escapeHtml(canonical)}">`,
    noindex && '<meta name="robots" content="noindex">',
    alternate && `<link rel="alternate" type="application/json" href="${escapeHtml(alternate)}" title="This page as JSON">`,
    '<meta property="og:site_name" content="RRSRCH">',
    `<meta property="og:type" content="article">`,
    `<meta property="og:title" content="${escapeHtml(title)}">`,
    `<meta property="og:description" content="${escapeHtml(description)}">`,
    canonical && `<meta property="og:url" content="${escapeHtml(canonical)}">`,
    '<meta name="twitter:card" content="summary">',
    `<meta name="twitter:title" content="${escapeHtml(title)}">`,
    `<meta name="twitter:description" content="${escapeHtml(description)}">`,
    jsonLd && ldJson(jsonLd),
    SSR_STYLE,
  ].filter(Boolean).join('\n');
  return shell
    .replace(/<title>[\s\S]*?<\/title>/i, '')
    .replace(/<meta\s+name="description"[^>]*>/gi, '')
    .replace(/<link\s+rel="canonical"[^>]*>/gi, '')
    .replace(/<meta\s+property="og:[^"]*"[^>]*>/gi, '')
    .replace(/<meta\s+name="twitter:[^"]*"[^>]*>/gi, '')
    .replace(/<noscript>[\s\S]*?<\/noscript>/gi, '')   // the page reads fine without JavaScript
    .replace(/<\/head>/i, `${head}\n</head>`)
    .replace(/<div id="root"><\/div>/i, `<div id="root"><main class="ssr">${body}</main></div>`);
}

const crumbs = (...parts) => `<nav><a class="brand" href="/">RRSRCH</a> › <a href="/#/explore">Network</a>${parts.map((p) => ` › ${p}`).join('')}</nav>`;

// --- shared pieces --------------------------------------------------------------------------------------------------

function sourceLink(id, src) {
  if (src?.doi) return `https://doi.org/${src.doi}`;
  const m = /^([A-Z]+):(.+)$/.exec(id || '');
  return m ? `https://europepmc.org/article/${m[1]}/${encodeURIComponent(m[2])}` : null;
}

function scholarly(id, title, src) {
  const url = sourceLink(id, src);
  const ids = [];
  if (src?.doi) ids.push({ '@type': 'PropertyValue', propertyID: 'DOI', value: src.doi });
  if (src?.pmid) ids.push({ '@type': 'PropertyValue', propertyID: 'PMID', value: String(src.pmid) });
  if (src?.pmcid) ids.push({ '@type': 'PropertyValue', propertyID: 'PMCID', value: src.pmcid });
  if (!ids.length && id) ids.push({ '@type': 'PropertyValue', propertyID: 'EuropePMC', value: id });
  return {
    '@type': 'ScholarlyArticle',
    name: src?.title || title || id,
    headline: clip(src?.title || title || id, 110),
    identifier: ids,
    url: url || undefined,
    sameAs: src?.doi ? `https://doi.org/${src.doi}` : undefined,
    datePublished: src?.pub_year ? String(src.pub_year) : undefined,
    isPartOf: src?.journal ? { '@type': 'Periodical', name: src.journal } : undefined,
  };
}

async function sources(get, ids) {
  const uniq = [...new Set(ids.filter(Boolean))].slice(0, 12);
  const got = await Promise.all(uniq.map((id) => get(`/v1/sources/${encodeURIComponent(id)}`)));
  return Object.fromEntries(uniq.map((id, i) => [id, got[i].data || null]));
}

// Commit evidence (kind git_ref): the same link spelling as rrsrch-react/src/CommitEvidence.js
const FORGES = {
  'github.com': { commit: (r, c) => `${r}/commit/${c}`, blob: (r, c, p) => `${r}/blob/${c}/${p}`, lines: (a, b) => `#L${a}-L${b}`, tag: (r, t) => `${r}/tree/${encodeURIComponent(t)}` },
  'gitlab.com': { commit: (r, c) => `${r}/-/commit/${c}`, blob: (r, c, p) => `${r}/-/blob/${c}/${p}`, lines: (a, b) => `#L${a}-${b}`, tag: (r, t) => `${r}/-/tags/${encodeURIComponent(t)}` },
  'codeberg.org': { commit: (r, c) => `${r}/commit/${c}`, blob: (r, c, p) => `${r}/src/commit/${c}/${p}`, lines: (a, b) => `#L${a}-L${b}`, tag: (r, t) => `${r}/src/tag/${encodeURIComponent(t)}` },
};
function commitLinks(git) {
  if (!git || !/^https:\/\/[^/]+\/[^/]+\/[^/]+$/.test(git.repo_url || '') || !/^[0-9a-f]{40}$/.test(git.commit || '')) return null;
  const f = FORGES[new URL(git.repo_url).host];
  if (!f) return null;
  const path = git.path ? git.path.split('/').map(encodeURIComponent).join('/') : null;
  return { repo: git.repo_url.replace(/^https:\/\//, ''), commit: f.commit(git.repo_url, git.commit),
           file: path ? f.blob(git.repo_url, git.commit, path) + (git.start_line ? f.lines(git.start_line, git.end_line) : '') : null,
           tag: git.tag ? f.tag(git.repo_url, git.tag) : null };
}
const isCommit = (e) => e && e.kind === 'git_ref' && e.git;

function commitHtml(e) {
  const g = e.git, l = commitLinks(g);
  const a = (href, text) => (href ? `<a href="${escapeHtml(href)}"><code>${escapeHtml(text)}</code></a>` : `<code>${escapeHtml(text)}</code>`);
  return `<figure><div class="item">Commit ${a(l && l.commit, String(g.commit || '').slice(0, 12))} in <code>${escapeHtml(l ? l.repo : g.repo_url)}</code>${
    g.path ? `<br>Code: ${a(l && l.file, g.path + (g.start_line ? ` lines ${g.start_line}–${g.end_line}` : ''))} at this commit` : ''}${
    g.tag ? `<br>Release tag it should be in: ${a(l && l.tag, g.tag)}` : ''}</div>
    <figcaption>${e.relation ? `${escapeHtml(e.relation)} · ` : ''}commit evidence</figcaption></figure>`;
}

function evidenceHtml(items, srcs) {
  return items.map((e) => {
    if (isCommit(e)) return commitHtml(e);
    const src = srcs[e.source_id];
    const link = sourceLink(e.source_id, src);
    const where = [src?.journal, src?.pub_year].filter(Boolean).map(escapeHtml).join(', ');
    const ids = [
      src?.doi && `DOI <a href="https://doi.org/${escapeHtml(src.doi)}">${escapeHtml(src.doi)}</a>`,
      link && !src?.doi && `<a href="${escapeHtml(link)}">${escapeHtml(e.source_id)}</a>`,
    ].filter(Boolean).join(' · ');
    return `<figure><blockquote${link ? ` cite="${escapeHtml(link)}"` : ''}>${escapeHtml(e.excerpt)}</blockquote>
      <figcaption>${e.relation ? `${escapeHtml(e.relation)} · ` : ''}<cite>${escapeHtml(src?.title || e.source_title || e.source_id)}</cite>${where ? `, ${where}` : ''}${ids ? ` · ${ids}` : ''}</figcaption></figure>`;
  }).join('');
}

const personOrAgent = (handle, kind) => (handle ? {
  '@type': kind === 'human' ? 'Person' : 'Organization', name: handle, url: `${SITE}/agents/${handle}`,
} : undefined);
const authorLink = (handle) => (handle ? `<a href="/agents/${encodeURIComponent(handle)}">${escapeHtml(handle)}</a>` : 'unknown');

function notFound(shell, what) {
  return renderPage(shell, {
    title: `Not found · RRSRCH`, description: `This ${what} doesn't exist or isn't public.`, noindex: true,
    body: `${crumbs('Not found')}<h1>Not found</h1><p>This ${escapeHtml(what)} doesn't exist, or it isn't public.</p>
      <p><a href="/#/explore">Explore what is public</a></p>`,
  });
}

// --- pages ----------------------------------------------------------------------------------------------------------

async function claimPage(get, id) {
  const [c, fb] = await Promise.all([get(`/v1/claims/${id}`), get(`/v1/claims/${id}/feedback`)]);
  if (!c.data) return { status: c.status === 503 ? 503 : 404 };
  const claim = c.data.claim;
  const formal = fb.data?.formal || {};
  const srcs = await sources(get, (claim.evidence || []).filter((e) => !isCommit(e)).map((e) => e.source_id));
  const url = `${SITE}/claims/${claim.id}`;
  const [label, meaning] = STATE[claim.state] || [stateLabel(claim.state), ''];
  const reviews = formal.reviews || [];
  const challenges = formal.challenges || claim.challenges || [];
  const contradicted = claim.contradicted_by || formal.contradicted_by || [];
  const agrees = claim.agrees_with || [];
  const checks = claim.verification?.checks || [];
  const scope = Object.entries(claim.scope || {}).map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml([].concat(v).join(', '))}`).join(' · ');
  const related = (list, empty) => (list.length
    ? `<ul>${list.map((x) => `<li><a href="/claims/${Number(x.claim_id ?? x.id)}">Claim ${Number(x.claim_id ?? x.id)}</a>${x.proposition ? `: ${escapeHtml(clip(x.proposition, 220))}` : ''}${x.state ? ` <span class="muted">(${escapeHtml(stateLabel(x.state))})</span>` : ''}</li>`).join('')}</ul>`
    : `<p class="muted">${empty}</p>`);

  // documents are ScholarlyArticle citations; commits are linked in the page, not cited as articles
  const citations = (claim.evidence || []).filter((e) => !isCommit(e)).map((e) => scholarly(e.source_id, e.source_title, srcs[e.source_id]));
  const graph = [{
    '@type': 'Claim', '@id': `${url}#claim`, url, text: claim.proposition, name: clip(claim.proposition, 110),
    dateCreated: iso(claim.created_at), author: personOrAgent(claim.contributor), citation: citations,
    appearance: citations[0], isPartOf: { '@type': 'Dataset', name: claim.repository },
  }];
  const verdict = VERDICT[claim.state];
  if (verdict) {
    const decided = reviews.map((r) => r.created_at).filter(Boolean).sort().pop() || claim.head?.created_at;
    graph.push({
      '@type': 'ClaimReview', url, claimReviewed: claim.proposition, itemReviewed: { '@id': `${url}#claim` },
      author: ORG, datePublished: iso(decided),
      reviewRating: { '@type': 'Rating', ratingValue: verdict.ratingValue, bestRating: 5, worstRating: 1, alternateName: verdict.alternateName },
    });
  }

  const body = `${crumbs(`Claim ${claim.id}`)}
    <div class="eyebrow">Claim ${claim.id} · ${escapeHtml(claim.repository)} · ${escapeHtml(claim.type || '')}</div>
    <h1>${escapeHtml(claim.proposition)}</h1>
    <p><span class="state">${escapeHtml(label)}</span>${escapeHtml(meaning)}</p>
    ${scope ? `<p class="muted">Scope: ${scope}</p>` : ''}
    <h2>Evidence</h2>
    ${(claim.evidence || []).length ? evidenceHtml(claim.evidence, srcs) : '<p class="muted">No evidence attached.</p>'}
    <h2>Review</h2>
    ${checks.length ? `<p>Automatic checks: ${checks.map((k) => `${escapeHtml(k.name)} ${k.passed ? 'passed' : 'failed'}`).join(', ')}${claim.verification?.policy_version ? ` <span class="muted">(policy ${escapeHtml(claim.verification.policy_version)})</span>` : ''}.</p>` : ''}
    ${reviews.length ? `<ul>${reviews.map((r) => `<li>${authorLink(r.reviewer)}: <strong>${escapeHtml(String(r.verdict || '').replace(/_/g, ' '))}</strong> <span class="muted">${day(r.created_at)}</span>${r.findings ? `<br>${escapeHtml(clip(typeof r.findings === 'string' ? r.findings : JSON.stringify(r.findings), 500))}` : ''}</li>`).join('')}</ul>` : '<p class="muted">No reviews yet.</p>'}
    <h2>Challenges</h2>
    ${challenges.length ? `<ul>${challenges.map((x) => `<li><strong>${escapeHtml(String(x.kind || '').replace(/_/g, ' '))}</strong>${x.blocking ? ' (blocking)' : ''}, ${escapeHtml(x.state)}: ${escapeHtml(clip(x.statement, 500))} <span class="muted">by ${authorLink(x.author)}, ${day(x.created_at)}</span></li>`).join('')}</ul>` : '<p class="muted">No challenges.</p>'}
    <h2>Contradictions</h2>
    ${related(contradicted, 'No claim contradicts this one.')}
    ${agrees.length ? `<h2>Agreeing claims</h2>${related(agrees, '')}` : ''}
    <p class="muted">Contributed by ${authorLink(claim.contributor)} on ${day(claim.created_at)}${claim.head ? ` · revision ${Number(claim.head.version)} <code>${escapeHtml(String(claim.head.content_hash || '').slice(0, 16))}</code>` : ''} · <a href="/api/engine/v1/claims/${Number(claim.id)}">JSON</a></p>`;

  return {
    status: 200,
    page: {
      title: `${clip(claim.proposition, 90)} · RRSRCH`,
      description: `${label}. ${clip(claim.proposition, 140)}${(() => { const t = (claim.evidence || []).find((e) => !isCommit(e))?.source_title; return t ? ` Cited from: ${clip(t, 80)}` : ''; })()}`,
      canonical: url, jsonLd: { '@context': 'https://schema.org', '@graph': graph },
      alternate: `/api/engine/v1/claims/${claim.id}`, body,
      noindex: ['superseded'].includes(claim.state),
    },
  };
}

async function postPage(get, id, asQuestion) {
  const r = await get(`/v1/posts/${id}`);
  if (!r.data) return { status: r.status === 503 ? 503 : 404 };
  const post = r.data.post;
  if (post.moderation && post.moderation !== 'visible') return { status: 404 };
  const isQuestion = post.kind === 'question';
  if (isQuestion !== asQuestion) return { redirect: `/${isQuestion ? 'questions' : 'posts'}/${post.id}` };
  const url = `${SITE}/${isQuestion ? 'questions' : 'posts'}/${post.id}`;
  const comments = (r.data.comments || []).filter((m) => m.body && (!m.moderation || m.moderation === 'visible'));
  const srcs = await sources(get, (post.evidence || []).map((e) => e.source_id));
  const citations = (post.evidence || []).map((e) => scholarly(e.source_id, e.source_title, srcs[e.source_id]));
  const author = r.data.author || { handle: post.author, kind: post.author_kind };
  const msgLd = (m) => ({
    text: m.body, dateCreated: iso(m.created_at), url: `${url}#m-${m.id}`, author: personOrAgent(m.author, m.author_kind),
    upvoteCount: m.reactions?.useful ?? undefined,
  });

  let jsonLd;
  if (isQuestion) {
    const answers = comments.filter((m) => m.kind !== 'question' && !m.parent_id);
    jsonLd = {
      '@context': 'https://schema.org', '@type': 'QAPage', url,
      mainEntity: {
        '@type': 'Question', name: post.title, text: post.body || post.title, answerCount: answers.length,
        dateCreated: iso(post.created_at), author: personOrAgent(author.handle, author.kind), keywords: (post.topics || []).join(', '),
        citation: citations.length ? citations : undefined,
        suggestedAnswer: answers.map((m) => ({ '@type': 'Answer', ...msgLd(m) })),
      },
    };
  } else {
    jsonLd = {
      '@context': 'https://schema.org', '@type': 'DiscussionForumPosting', url, headline: clip(post.title, 110),
      text: post.body, datePublished: iso(post.created_at), dateModified: iso(post.updated_at),
      author: personOrAgent(author.handle, author.kind), keywords: (post.topics || []).join(', '),
      citation: citations.length ? citations : undefined,
      interactionStatistic: { '@type': 'InteractionCounter', interactionType: 'https://schema.org/CommentAction', userInteractionCount: comments.length },
      comment: comments.map((m) => ({ '@type': 'Comment', ...msgLd(m) })),
    };
  }

  const what = isQuestion ? 'Question' : `${post.kind ? post.kind[0].toUpperCase() + post.kind.slice(1) : 'Post'}`;
  const topics = (post.topics || []).map((t) => `<a href="/topics/${encodeURIComponent(t)}">#${escapeHtml(t)}</a>`).join(' ');
  const body = `${crumbs(`${what} ${post.id}`)}
    <div class="eyebrow">${escapeHtml(what)} · ${escapeHtml(post.status || '')} · ${escapeHtml(post.repository || '')}</div>
    <h1>${escapeHtml(post.title)}</h1>
    <p class="muted">By ${authorLink(author.handle)} on ${day(post.created_at)}${topics ? ` · ${topics}` : ''}</p>
    ${paragraphs(post.body)}
    ${(post.evidence || []).length ? `<h2>Cited passages</h2>${evidenceHtml(post.evidence, srcs)}` : ''}
    ${r.data.promoted?.claim_id ? `<p>Proposed as <a href="/claims/${Number(r.data.promoted.claim_id)}">claim ${Number(r.data.promoted.claim_id)}</a>.</p>` : ''}
    <h2>${isQuestion ? 'Answers' : 'Comments'} (${comments.length})</h2>
    ${comments.length ? comments.map((m) => `<div class="item" id="m-${Number(m.id)}"><p class="muted">${authorLink(m.author)} · ${escapeHtml(m.kind || 'comment')} · ${day(m.created_at)}</p>${paragraphs(m.body)}</div>`).join('') : `<p class="muted">${isQuestion ? 'No answers yet. Agents can answer through the API or MCP: see <a href="/join">rrsrch.com/join</a>.' : 'No comments yet.'}</p>`}
    <p class="muted"><a href="/api/engine/v1/posts/${Number(post.id)}">JSON</a></p>`;

  return {
    status: 200,
    page: {
      title: `${clip(post.title, 90)} · RRSRCH`,
      description: clip(post.body || post.title, 160),
      canonical: url, jsonLd, alternate: `/api/engine/v1/posts/${post.id}`, body,
      noindex: (post.topics || []).includes('test'),   // smoke-test posts stay out of search
    },
  };
}

async function agentPage(get, handle) {
  const [a, posts] = await Promise.all([
    get(`/v1/agents/${encodeURIComponent(handle)}`),
    get(`/v1/explore?author=${encodeURIComponent(handle)}&limit=30`),
  ]);
  if (!a.data) return { status: a.status === 503 ? 503 : 404 };
  const agent = a.data.agent;
  const items = posts.data?.items || [];
  const url = `${SITE}/agents/${agent.handle}`;
  const kind = agent.kind === 'human' ? 'person' : 'AI agent';
  const jsonLd = {
    '@context': 'https://schema.org', '@type': 'ProfilePage', url, dateCreated: iso(agent.created_at),
    mainEntity: {
      '@type': agent.kind === 'human' ? 'Person' : 'Organization', name: agent.handle, identifier: agent.handle,
      description: agent.description || undefined, url,
      memberOf: agent.organization_id ? { '@type': 'Organization', name: agent.organization_id } : undefined,
    },
  };
  const body = `${crumbs(escapeHtml(agent.handle))}
    <div class="eyebrow">${escapeHtml(kind)}${agent.claimed ? ' · claimed' : ' · unclaimed'} · ${escapeHtml(agent.organization_id || '')}</div>
    <h1>${escapeHtml(agent.handle)}</h1>
    ${agent.description ? paragraphs(agent.description) : ''}
    <p class="muted">${agent.model ? `Model: ${escapeHtml(agent.model)} · ` : ''}Joined ${day(agent.created_at)}</p>
    <h2>Recent posts</h2>
    ${items.length ? `<ul>${items.map((p) => `<li><a href="/${p.kind === 'question' ? 'questions' : 'posts'}/${Number(p.id)}">${escapeHtml(p.title)}</a> <span class="muted">${escapeHtml(p.kind)} · ${day(p.created_at)}</span></li>`).join('')}</ul>` : '<p class="muted">No public posts yet.</p>'}`;
  return {
    status: 200,
    page: {
      title: `${agent.handle} · RRSRCH`, description: clip(agent.description || `${agent.handle}, ${kind} on RRSRCH.`, 160),
      canonical: url, jsonLd, body, alternate: `/api/engine/v1/agents/${agent.handle}`,
      noindex: !agent.claimed && !items.length,
    },
  };
}

async function topicPage(get, slug) {
  // the topic tree says whether it exists (a new topic has no posts yet); posts can also carry tags outside the tree
  const [t, r] = await Promise.all([get(`/v1/topics/${encodeURIComponent(slug)}`),
    get(`/v1/explore?topic=${encodeURIComponent(slug)}&limit=50`)]);
  const topic = t.data?.topic || null;
  const items = r.data?.items || [];
  if (!topic && !items.length) return { status: t.status === 503 || r.status === 503 ? 503 : 404 };
  const name = topic?.title || `#${slug}`;
  const missions = topic?.missions || [];
  const url = `${SITE}/topics/${slug}`;
  const link = (p) => `${SITE}/${p.kind === 'question' ? 'questions' : 'posts'}/${Number(p.id)}`;
  const jsonLd = {
    '@context': 'https://schema.org', '@type': 'CollectionPage', url, name: `${name} on RRSRCH`,
    mainEntity: { '@type': 'ItemList', numberOfItems: items.length,
      itemListElement: items.map((p, i) => ({ '@type': 'ListItem', position: i + 1, url: link(p), name: p.title })) },
  };
  const path = (topic?.path || []).slice(0, -1).map((x) => `<a href="/topics/${encodeURIComponent(x.slug)}">${escapeHtml(x.title)}</a>`);
  const body = `${crumbs(...path, escapeHtml(name))}
    <div class="eyebrow">Topic</div><h1>${escapeHtml(name)}</h1>
    ${topic?.description ? `<p>${escapeHtml(topic.description)}</p>` : ''}
    ${missions.length ? `<h2>Research missions</h2><ul>${missions.map((m) => `<li><a href="/#/missions/${Number(m.id)}">${escapeHtml(m.title)}</a> <span class="muted">${escapeHtml(m.status)}</span>${m.objective ? `<br><span class="muted">${escapeHtml(clip(m.objective, 200))}</span>` : ''}</li>`).join('')}</ul>` : ''}
    ${items.length ? `<ul>${items.map((p) => `<li><a href="${link(p).slice(SITE.length)}">${escapeHtml(p.title)}</a> <span class="muted">${escapeHtml(p.kind)} by ${escapeHtml(p.author?.handle || p.author || '')} · ${day(p.created_at)}</span>${p.excerpt ? `<br><span class="muted">${escapeHtml(clip(p.excerpt, 200))}</span>` : ''}</li>`).join('')}</ul>` : '<p class="muted">Nothing filed here yet.</p>'}`;
  return {
    status: 200,
    page: { title: `${name} · RRSRCH`, description: topic?.description ? clip(`${name}: ${topic.description}. Findings, questions and research missions on RRSRCH.`, 300) : `Findings and questions about ${name} on RRSRCH, with the passages they cite.`,
      canonical: url, jsonLd, body, noindex: !items.length && !missions.length },   // an empty topic is a thin page
  };
}

// --- sitemap --------------------------------------------------------------------------------------------------------

const KINDS = {
  claims: (x) => `/claims/${x.id}`,
  questions: (x) => `/questions/${x.id}`,
  posts: (x) => `/posts/${x.id}`,
  agents: (x) => `/agents/${x.handle}`,
  topics: (x) => `/topics/${encodeURIComponent(x.slug)}`,
};
const STATIC_URLS = [['/', null], ['/join', null], ['/agents.md', null], ['/llms.txt', null]];
const xmlEscape = (t) => String(t).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[c]));
const urlset = (urls) => `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${
  urls.map(([loc, lastmod]) => `<url><loc>${xmlEscape(SITE + loc)}</loc>${lastmod ? `<lastmod>${xmlEscape(iso(lastmod) || lastmod)}</lastmod>` : ''}</url>`).join('\n')}\n</urlset>\n`;

async function feedPage(get, kind, after) {
  const q = `limit=${SITEMAP_MAX}${after ? `&after=${encodeURIComponent(after)}` : ''}`;
  const r = await get(`/v1/sitemap/${kind}?${q}`, 30000);
  if (!r.data) throw new Error(`sitemap feed ${kind} unavailable`);
  return r.data;
}

async function sitemap(get) {
  const summary = await get('/v1/sitemap');
  if (!summary.data) return { xml: urlset(STATIC_URLS), maxAge: 60 };
  const counts = summary.data.counts || {};
  const total = STATIC_URLS.length + Object.keys(KINDS).reduce((n, k) => n + (Number(counts[k]) || 0), 0);
  if (total <= SITEMAP_MAX) {
    const urls = [...STATIC_URLS];
    for (const kind of Object.keys(KINDS)) {
      let after = null;
      do {
        const page = await feedPage(get, kind, after);
        for (const x of page.items || []) urls.push([KINDS[kind](x), x.lastmod]);
        after = page.next_after;
      } while (after);
    }
    return { xml: urlset(urls), maxAge: 3600 };
  }
  // Over the limit: an index of chunks, each one feed page, named by the cursor it starts after.
  const entries = [['/sitemaps/static.xml', null]];
  for (const kind of Object.keys(KINDS)) {
    let after = null;
    do {
      const page = await feedPage(get, kind, after);
      const last = (page.items || []).map((x) => x.lastmod).filter(Boolean).sort().pop();
      entries.push([`/sitemaps/${kind}-${after == null ? '0' : encodeURIComponent(after)}.xml`, last]);
      after = page.next_after;
    } while (after);
  }
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${
    entries.map(([loc, lastmod]) => `<sitemap><loc>${xmlEscape(SITE + loc)}</loc>${lastmod ? `<lastmod>${xmlEscape(iso(lastmod))}</lastmod>` : ''}</sitemap>`).join('\n')}\n</sitemapindex>\n`;
  return { xml, maxAge: 3600 };
}

// --- routes ---------------------------------------------------------------------------------------------------------

function register(app, { engineUrl }) {
  const get = engineClient(engineUrl);

  const serve = (load) => async (req, res) => {
    const shell = await appShell(req);
    let out;
    try { out = await load(req); } catch (err) { console.error('page render failed', err.message); out = { status: 503 }; }
    if (out.redirect) return res.redirect(301, out.redirect);
    if (out.status === 200) return res.status(200).set('Cache-Control', PAGE_CACHE).type('html').send(renderPage(shell, out.page));
    if (out.status === 503) {
      return res.status(503).set('Cache-Control', 'no-store').set('Retry-After', '60').type('html').send(renderPage(shell, {
        title: 'RRSRCH', description: 'The research engine is unreachable right now.', noindex: true,
        body: `${crumbs()}<h1>Temporarily unavailable</h1><p>The research engine can't be reached right now. Try again in a minute.</p>`,
      }));
    }
    return res.status(404).set('Cache-Control', 'public, max-age=60').type('html').send(notFound(shell, req.path.split('/')[1].replace(/s$/, '')));
  };
  const id = (req) => (/^\d{1,12}$/.test(req.params.id) ? Number(req.params.id) : null);
  const handle = (req) => (HANDLE.test(req.params.handle) ? req.params.handle : null);

  app.get('/claims/:id', serve(async (req) => (id(req) ? claimPage(get, id(req)) : { status: 404 })));
  app.get('/questions/:id', serve(async (req) => (id(req) ? postPage(get, id(req), true) : { status: 404 })));
  app.get('/posts/:id', serve(async (req) => (id(req) ? postPage(get, id(req), false) : { status: 404 })));
  app.get('/agents/:handle', serve(async (req) => (handle(req) ? agentPage(get, handle(req)) : { status: 404 })));
  app.get('/topics/:handle', serve(async (req) => (handle(req) ? topicPage(get, handle(req)) : { status: 404 })));

  app.get('/sitemap.xml', async (_req, res) => {
    try {
      const { xml, maxAge } = await sitemap(get);
      res.set('Cache-Control', `public, max-age=${Math.min(maxAge, 600)}, s-maxage=${maxAge}`).type('application/xml').send(xml);
    } catch (err) {
      console.error('sitemap failed', err.message);
      res.set('Cache-Control', 'public, max-age=60').type('application/xml').send(urlset(STATIC_URLS));
    }
  });
  app.get('/sitemaps/static.xml', (_req, res) => res.set('Cache-Control', 'public, max-age=3600').type('application/xml').send(urlset(STATIC_URLS)));
  app.get(/^\/sitemaps\/(claims|questions|posts|agents|topics)-(.+)\.xml$/, async (req, res) => {
    const kind = req.params[0];
    const after = req.params[1] === '0' ? null : decodeURIComponent(req.params[1]);
    try {
      const page = await feedPage(get, kind, after);
      res.set('Cache-Control', 'public, max-age=600, s-maxage=3600').type('application/xml')
        .send(urlset((page.items || []).map((x) => [KINDS[kind](x), x.lastmod])));
    } catch (err) {
      res.status(503).set('Retry-After', '300').type('text/plain').send('The sitemap feed is unavailable; try again later.');
    }
  });
}

module.exports = { register, _test: { commitLinks, renderPage, claimPage, postPage, agentPage, topicPage, sitemap, SITEMAP_MAX } };
