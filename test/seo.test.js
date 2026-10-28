// Server-rendered pages and the sitemap (seo.js), against a fake engine.  Run: npm run test:server
const test = require('node:test');
const assert = require('node:assert');
const express = require('express');
const seo = require('../seo');

const CLAIM = {
  ok: true,
  claim: {
    id: 3, repository: 'rrsrch/msc-knee-oa', type: 'empirical', state: 'supported',
    proposition: 'Cartilage defects were covered with <soft> tissue at 42 weeks.', scope: { joint: ['knee'] },
    contributor: 'rrsrch-reader', created_at: '2026-10-12T20:39:44Z', head: { version: 1, content_hash: 'f846e2c0', created_at: '2026-10-13T00:00:00Z' },
    evidence: [{ relation: 'supports', source_id: 'MED:11869080', source_title: 'Human autologous MSC transplantation', excerpt: 'Forty-two weeks after transplantation, the defects were covered.' }],
    verification: { checks: [{ name: 'span_hash', passed: true }], policy_version: 'msc-v1' },
    contradicted_by: [{ claim_id: 9, proposition: 'No coverage at 42 weeks.', state: 'structurally_valid' }], agrees_with: [],
  },
};
const FEEDBACK = { ok: true, formal: { reviews: [{ reviewer: 'ada', verdict: 'accept', created_at: '2026-10-14T00:00:00Z' }], challenges: [] } };
// the engine's real shape: /v1/sources/<id> is {ok, source}
const SOURCE = { ok: true, source: { id: 'MED:11869080', kind: 'paper', doi: '10.1016/j.joca.2002.0001', title: 'Human autologous MSC transplantation', journal: 'Osteoarthritis Cartilage', pub_year: 2002 } };
const URL_SOURCE = { ok: true, source: { id: 'URL:18765dd9591466dceb7b4f29', kind: 'url', doi: null, title: 'Term Premium on a 10 Year Zero Coupon Bond | FRED',
  url: 'https://fred.stlouisfed.org/series/THREEFYTP10', provenance: 'fetched' } };
const QUESTION = { ok: true, post: { id: 5, kind: 'question', title: 'Do gains last past 24 months?', body: 'Asking about <b>long</b> follow-up.', topics: ['knee-oa'], evidence: [], status: 'open', moderation: 'visible', created_at: '2026-10-14T00:00:00Z' },
  author: { handle: 'ada', kind: 'human' }, comments: [{ id: 11, author: 'bot', author_kind: 'model', kind: 'answer', body: 'One trial reports 4 years.', moderation: 'visible', created_at: '2026-10-14T01:00:00Z', parent_id: null }] };

let routes;
let server;
let feedCounts = { claims: 2, questions: 1, posts: 0, agents: 1, topics: 1 };
function fakeEngine(url) {
  const p = new URL(url).pathname + new URL(url).search;
  if (p === '/v1/claims/3') return CLAIM;
  if (p === '/v1/claims/3/feedback') return FEEDBACK;
  if (p.startsWith('/v1/sources/URL')) return URL_SOURCE;
  if (p.startsWith('/v1/sources/')) return SOURCE;
  if (p === '/v1/posts/5') return QUESTION;
  if (p === '/v1/topics/cybersecurity') return { ok: true, topic: { slug: 'cybersecurity', title: 'Cybersecurity', description: 'Vulnerabilities & patches',
    path: [{ slug: 'technology', title: 'Technology' }, { slug: 'cybersecurity', title: 'Cybersecurity' }],
    missions: [{ id: 4, title: 'Can agents validate a patch?', status: 'open', objective: 'Pick public advisories.' }] } };
  if (p === '/v1/topics/empty') return { ok: true, topic: { slug: 'empty', title: 'Empty', description: '', path: [{ slug: 'empty', title: 'Empty' }], missions: [] } };
  if (p.startsWith('/v1/explore?topic=knee-oa')) return { ok: true, items: [{ id: 5, kind: 'question', title: 'Do gains last past 24 months?', author: { handle: 'ada' }, created_at: '2026-10-14T00:00:00Z' }] };
  if (p.startsWith('/v1/explore?topic=')) return { ok: true, items: [] };
  if (p === '/v1/sitemap') return { ok: true, counts: feedCounts };
  const m = /^\/v1\/sitemap\/(\w+)\?limit=\d+(?:&after=(.+))?$/.exec(p);
  if (m) {
    const items = { claims: [{ id: 1, lastmod: '2026-10-01T00:00:00Z' }, { id: 3, lastmod: '2026-10-14T00:00:00Z' }],
      questions: [{ id: 5, lastmod: '2026-10-14T00:00:00Z' }], posts: [], agents: [{ handle: 'ada', lastmod: '2026-10-14T00:00:00Z' }],
      topics: [{ slug: 'knee-oa', lastmod: '2026-10-14T00:00:00Z' }] }[m[1]];
    return { ok: true, kind: m[1], items, next_after: null };
  }
  return null;
}

test.before(async () => {
  global.fetch = async (url) => {
    if (String(url).endsWith('/index.html')) return { ok: true, status: 200, text: async () => '<html><head><title>x</title></head><body><div id="root"></div></body></html>' };
    const body = fakeEngine(String(url));
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { detail: 'Not Found' } };
  };
  const app = express();
  seo.register(app, { engineUrl: 'http://engine.test' });
  server = app.listen(0);
  routes = `http://127.0.0.1:${server.address().port}`;
});
test.after(() => server.close());

const realFetch = require('node:http');
async function get(path) {
  return new Promise((resolve) => {
    realFetch.get(routes + path, (res) => {
      let b = ''; res.on('data', (c) => { b += c; }); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: b }));
    });
  });
}
// the page's own JSON-LD (the app shell carries the site-wide Organization/WebSite block too)
const ld = (html) => [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((m) => JSON.parse(m[1]))
  .filter((d) => !(d['@graph'] || []).some((x) => x['@type'] === 'WebSite'));

test('a claim renders its passage, source DOI, state and contradictions, inside #root', async () => {
  const r = await get('/claims/3');
  assert.equal(r.status, 200);
  assert.match(r.body, /<div id="root"><main class="ssr">/);
  assert.match(r.body, /Forty-two weeks after transplantation/);
  assert.match(r.body, /https:\/\/doi\.org\/10\.1016\/j\.joca\.2002\.0001/);
  assert.match(r.body, /<span class="state">Supported<\/span>/);
  assert.match(r.body, /<a href="\/claims\/9">Claim 9<\/a>/);
  assert.match(r.body, /&lt;soft&gt;/, 'agent text is escaped');
  assert.match(r.body, /<link rel="canonical" href="https:\/\/rrsrch\.com\/claims\/3">/);
  assert.equal((r.body.match(/<title>/g) || []).length, 1);
});

test('a reviewed claim is a Claim with a ClaimReview; its sources are ScholarlyArticles', async () => {
  const [doc] = ld((await get('/claims/3')).body);
  const claim = doc['@graph'].find((x) => x['@type'] === 'Claim');
  const review = doc['@graph'].find((x) => x['@type'] === 'ClaimReview');
  assert.equal(claim.citation[0]['@type'], 'ScholarlyArticle');
  assert.equal(claim.citation[0].sameAs, 'https://doi.org/10.1016/j.joca.2002.0001');
  assert.equal(review.reviewRating.ratingValue, 5);
  assert.deepEqual(review.itemReviewed, { '@id': 'https://rrsrch.com/claims/3#claim' });
});

test('an unreviewed claim gets no ClaimReview: automatic checks are not a verdict', async () => {
  CLAIM.claim.state = 'structurally_valid';
  try {
    const [doc] = ld((await get('/claims/3')).body);
    assert.ok(!doc['@graph'].some((x) => x['@type'] === 'ClaimReview'));
  } finally { CLAIM.claim.state = 'supported'; }
});

test('a question is a QAPage with its answers; /posts/N of a question redirects to /questions/N', async () => {
  const r = await get('/questions/5');
  assert.equal(r.status, 200);
  const [doc] = ld(r.body);
  assert.equal(doc['@type'], 'QAPage');
  assert.equal(doc.mainEntity.answerCount, 1);
  assert.equal(doc.mainEntity.suggestedAnswer[0].text, 'One trial reports 4 years.');
  assert.match(r.body, /Asking about &lt;b&gt;long&lt;\/b&gt;/);
  const moved = await get('/posts/5');
  assert.equal(moved.status, 301);
  assert.equal(moved.headers.location, '/questions/5');
});

test('commit evidence is shown and linked, never as a blank source or an article citation', async () => {
  const commit = { id: 9, relation: 'supports', kind: 'git_ref', source_id: null, source_title: null, excerpt: 'github.com/o/r@0123456789ab',
    git: { repo_url: 'https://github.com/o/r', commit: '0123456789abcdef0123456789abcdef01234567', tag: 'v1.2.3', path: 'src/a.py', start_line: 3, end_line: 9 } };
  CLAIM.claim.evidence.push(commit);
  try {
    const r = await get('/claims/3');
    assert.equal(r.status, 200);
    assert.match(r.body, /href="https:\/\/github\.com\/o\/r\/commit\/0123456789abcdef0123456789abcdef01234567"/);
    assert.match(r.body, /href="https:\/\/github\.com\/o\/r\/blob\/0123456789abcdef0123456789abcdef01234567\/src\/a\.py#L3-L9"/);
    assert.match(r.body, /Release tag it should be in/);
    assert.doesNotMatch(r.body, /\(null\)|>null</);
    const [doc] = ld(r.body);
    const claim = doc['@graph'].find((x) => x['@type'] === 'Claim');
    assert.equal(claim.citation.length, 1, 'only the document is a ScholarlyArticle citation');
  } finally { CLAIM.claim.evidence.pop(); }
  const { commitLinks } = seo._test;
  assert.equal(commitLinks({ repo_url: 'https://gitlab.com/o/r', commit: 'a'.repeat(40), path: 'x.py', start_line: 1, end_line: 2 }).file,
    `https://gitlab.com/o/r/-/blob/${'a'.repeat(40)}/x.py#L1-2`);
  assert.equal(commitLinks({ repo_url: 'https://example.com/o/r', commit: 'a'.repeat(40) }), null);
});

test('missing or malformed content is a 404 with noindex', async () => {
  for (const p of ['/claims/404', '/claims/abc', '/agents/Not_A_Handle']) {
    const r = await get(p);
    assert.equal(r.status, 404, p);
    assert.match(r.body, /<meta name="robots" content="noindex">/);
  }
});

test('a topic in the tree renders under its title even before anything is filed in it', async () => {
  const r = await get('/topics/cybersecurity');
  assert.equal(r.status, 200);
  assert.match(r.body, /<title>Cybersecurity · RRSRCH<\/title>/);
  assert.match(r.body, /<a href="\/topics\/technology">Technology<\/a> › Cybersecurity/);
  assert.match(r.body, /<a href="\/#\/missions\/4">Can agents validate a patch\?<\/a>/);
  assert.match(r.body, /Vulnerabilities &amp; patches/);
  assert.doesNotMatch(r.body, /noindex/);
  const empty = await get('/topics/empty');
  assert.equal(empty.status, 200);
  assert.match(empty.body, /<title>Empty · RRSRCH<\/title>/);
  assert.match(empty.body, /<meta name="robots" content="noindex">/);   // nothing in it yet: a thin page
  const tag = await get('/topics/knee-oa');                                  // a post tag outside the tree
  assert.equal(tag.status, 200);
  assert.match(tag.body, /<title>#knee-oa · RRSRCH<\/title>/);
  assert.equal((await get('/topics/no-such-topic')).status, 404);
});

test('the sitemap lists every public item with its lastmod, as one urlset under the limit', async () => {
  const r = await get('/sitemap.xml');
  assert.match(r.body, /<urlset/);
  assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/claims\/3<\/loc><lastmod>2026-10-14T00:00:00.000Z<\/lastmod>/);
  assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/questions\/5<\/loc>/);
  assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/agents\/ada<\/loc>/);
  assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/topics\/knee-oa<\/loc>/);
  assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/join<\/loc>/);
});

test('over 50,000 URLs the sitemap becomes an index of chunks', async () => {
  feedCounts = { claims: 60000, questions: 1, posts: 0, agents: 1, topics: 1 };
  try {
    const r = await get('/sitemap.xml');
    assert.match(r.body, /<sitemapindex/);
    assert.match(r.body, /<loc>https:\/\/rrsrch\.com\/sitemaps\/claims-0\.xml<\/loc>/);
    const chunk = await get('/sitemaps/claims-0.xml');
    assert.match(chunk.body, /<loc>https:\/\/rrsrch\.com\/claims\/1<\/loc>/);
  } finally { feedCounts = { claims: 2, questions: 1, posts: 0, agents: 1, topics: 1 }; }
});

test('a fetched web page links to where it was fetched from, never to Europe PMC', async () => {
  QUESTION.post.evidence.push({ source_id: 'URL:18765dd9591466dceb7b4f29', source_title: 'Term Premium | FRED', excerpt: 'Term Premium on a 10 Year Zero Coupon Bond',
    source_url: 'https://fred.stlouisfed.org/series/THREEFYTP10' });
  try {
    const r = await get('/questions/5');
    assert.doesNotMatch(r.body, /europepmc\.org\/article\/URL/);
    assert.match(r.body, /<a href="https:\/\/fred\.stlouisfed\.org\/series\/THREEFYTP10">fred\.stlouisfed\.org<\/a>/);
    const [doc] = ld(r.body);
    const cites = doc.mainEntity.citation;
    assert.deepEqual(cites.map((c) => [c['@type'], c.url]), [['WebPage', 'https://fred.stlouisfed.org/series/THREEFYTP10']]);
  } finally { QUESTION.post.evidence.pop(); }
});
