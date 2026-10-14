const express = require('express');
const { TwitterApi } = require('twitter-api-v2');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');
const passport = require('passport');
const GoogleStrategy = require('passport-google-oauth20').Strategy;
const session = require('express-session');
const bcrypt = require('bcrypt');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors({
  origin: process.env.FRONTEND_URL || 'http://localhost:3000',
  credentials: true
}));
app.use(express.json());
app.use(session({
  secret: process.env.SESSION_SECRET || 'rrsrch-secret-key-2025',
  resave: false,
  saveUninitialized: false,
  cookie: {
    secure: process.env.NODE_ENV === 'production',
    httpOnly: true,
    maxAge: 24 * 60 * 60 * 1000 // 24 hours
  }
}));
app.use(passport.initialize());
app.use(passport.session());

// Initialize Twitter client
const twitterClient = new TwitterApi(process.env.TWITTER_BEARER_TOKEN);

// Configure Google OAuth Strategy (only when credentials are configured —
// the strategy constructor throws if clientID/clientSecret are missing).
const googleOAuthEnabled = !!(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
if (googleOAuthEnabled) {
  passport.use(new GoogleStrategy({
      clientID: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
      callbackURL: `${process.env.FRONTEND_URL || 'http://localhost:3000'}/api/auth/google/callback`
    },
    function(accessToken, refreshToken, profile, cb) {
      // Here you would normally save the user to a database
      // For now, we'll just return the profile
      return cb(null, {
        id: profile.id,
        name: profile.displayName,
        email: profile.emails[0].value,
        picture: profile.photos[0].value
      });
    }
  ));
}

passport.serializeUser((user, done) => {
  done(null, user);
});

passport.deserializeUser((user, done) => {
  done(null, user);
});

// --- Posts storage ---
// On Vercel the filesystem is read-only, so persist posts in Vercel Blob when a
// BLOB_READ_WRITE_TOKEN is present. Locally (dev) fall back to a JSON file on disk.
const POSTS_FILE = path.join(__dirname, 'posts.json');
const BLOB_KEY = 'posts.json';
const useBlob = !!process.env.BLOB_READ_WRITE_TOKEN;
// Which persistence the process actually got. Without the blob token this silently
// falls back to a local file, which on serverless is a read-only empty disk — every
// account vanishes and nothing says why.
console.log(useBlob
  ? 'storage: vercel blob'
  : 'storage: LOCAL FILE — BLOB_READ_WRITE_TOKEN is not set in this environment');

async function readPosts() {
  if (useBlob) {
    const { list } = require('@vercel/blob');
    const { blobs } = await list({ prefix: BLOB_KEY });
    const match = blobs.find((b) => b.pathname === BLOB_KEY);
    if (!match) return [];
    const res = await fetch(match.url, { cache: 'no-store' });
    if (!res.ok) return [];
    return res.json();
  }
  try {
    const data = await fs.readFile(POSTS_FILE, 'utf8');
    return JSON.parse(data);
  } catch {
    return [];
  }
}

async function writePosts(posts) {
  if (useBlob) {
    const { put } = require('@vercel/blob');
    await put(BLOB_KEY, JSON.stringify(posts, null, 2), {
      access: 'public',
      contentType: 'application/json',
      addRandomSuffix: false,
      allowOverwrite: true,
    });
    return;
  }
  await fs.writeFile(POSTS_FILE, JSON.stringify(posts, null, 2));
}

// Initialize local posts file if it doesn't exist (dev only; no-op on Vercel)
async function initPostsFile() {
  if (useBlob) return;
  try {
    await fs.access(POSTS_FILE);
  } catch {
    try {
      await fs.writeFile(POSTS_FILE, JSON.stringify([], null, 2));
    } catch {
      // read-only filesystem; reads will just return []
    }
  }
}

const EUROPE_PMC_SEARCH = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search';
// Local evidence engine (rrsrch serve). Unset = site falls back to demo/PMC.
const ENGINE_URL = (process.env.RRSRCH_ENGINE_URL || '').replace(/\/$/, '');

// Short-lived answer cache (writer is slow; Cloudflare/Vercel otherwise 524).
const engineAnswerCache = new Map();
const ENGINE_ANSWER_TTL_MS = 30 * 60 * 1000;

// Evidence-engine answer (proxies to rrsrch serve when RRSRCH_ENGINE_URL is set).
app.post('/api/engine/answer', async (req, res) => {
  if (!ENGINE_URL) {
    return res.status(503).json({
      ok: false,
      error: 'engine offline',
      detail: 'Set RRSRCH_ENGINE_URL to a running `rrsrch serve` instance.',
    });
  }
  const question = String(req.body?.question || '').trim();
  if (!question) return res.status(400).json({ ok: false, error: 'question required' });
  if (question.length > 800) return res.status(400).json({ ok: false, error: 'question too long' });
  const cacheKey = question.toLowerCase();
  const cached = engineAnswerCache.get(cacheKey);
  if (cached && (Date.now() - cached.at) < ENGINE_ANSWER_TTL_MS) {
    return res.json({ ...cached.data, cached: true });
  }
  try {
    const upstream = await fetch(`${ENGINE_URL}/v1/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal: AbortSignal.timeout(300000),
    });
    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return res.status(upstream.status >= 400 ? upstream.status : 502).json(
        data.error ? data : { ok: false, error: 'engine error' },
      );
    }
    engineAnswerCache.set(cacheKey, { at: Date.now(), data });
    return res.json(data);
  } catch (err) {
    console.error('engine answer failed', err);
    return res.status(502).json({ ok: false, error: 'could not reach evidence engine' });
  }
});

app.get('/api/engine/health', async (_req, res) => {
  if (!ENGINE_URL) return res.json({ ok: false, configured: false });
  try {
    const upstream = await fetch(`${ENGINE_URL}/v1/health`, { signal: AbortSignal.timeout(5000) });
    const data = await upstream.json().catch(() => ({}));
    return res.status(upstream.ok ? 200 : 503).json({ configured: true, ...data });
  } catch {
    return res.status(503).json({ ok: false, configured: true, error: 'unreachable' });
  }
});

// Engine API (knowledge, agents, review, collaboration) for the site's Agents page. The browser sends its
// own engine API key; the engine decides every permission, this only forwards. It also gives MCP clients a
// stable base URL (https://rrsrch.com/api/engine) while the engine's own address changes.
const ENGINE_FORWARD_HEADERS = ['authorization', 'idempotency-key'];
const ENGINE_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE']);
app.all('/api/engine/v1/*', async (req, res) => {
  if (!ENGINE_URL) return res.status(503).json({ ok: false, error: 'engine offline' });
  if (!ENGINE_METHODS.has(req.method)) return res.status(405).json({ ok: false, error: 'method not allowed' });
  const path = req.originalUrl.replace(/^\/api\/engine/, '');
  let decoded;
  try { decoded = decodeURIComponent(path.split('?')[0]); } catch { decoded = '..'; }
  if (!path.startsWith('/v1/') || decoded.includes('..') || decoded.includes('\\')) {
    return res.status(400).json({ ok: false, error: 'bad engine path' });
  }
  const headers = {};
  for (const h of ENGINE_FORWARD_HEADERS) if (req.headers[h]) headers[h] = req.headers[h];
  const hasBody = req.method !== 'GET' && req.method !== 'DELETE';
  if (hasBody) headers['content-type'] = 'application/json';
  try {
    const upstream = await fetch(`${ENGINE_URL}${path}`, {
      method: req.method,
      headers,
      body: hasBody ? JSON.stringify(req.body ?? {}) : undefined,
      signal: AbortSignal.timeout(60000),
    });
    const text = await upstream.text();
    res.status(upstream.status);
    res.type(upstream.headers.get('content-type') || 'application/json');
    return res.send(text);
  } catch (err) {
    console.error('engine proxy failed', err);
    return res.status(502).json({ ok: false, error: 'could not reach evidence engine' });
  }
});

// Open-web search (Comet-like layer). Prefer Brave, then Serper. Not the evidence ledger.
function hostnameOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return null; }
}

function faviconFor(url, source) {
  const host = source || hostnameOf(url);
  if (!host) return null;
  return `https://icons.duckduckgo.com/ip3/${host}.ico`;
}

/** Classify open-web hostnames into trust buckets for the Web tab. */
function classifyWebKind(url, source) {
  const host = String(source || hostnameOf(url) || '').toLowerCase();
  if (!host) return 'clinic';
  if (
    /\.gov(\.|$)/.test(host)
    || /(fda|cdc|nih|who\.int|ema\.europa|nhs\.uk|nice\.org|health\.gov)/.test(host)
  ) return 'authority';
  if (
    /(reddit\.com|quora\.com|stackoverflow\.com|discourse\.|forum\.|patient\.info|healthunlocked)/.test(host)
  ) return 'forum';
  if (
    /(nytimes|washingtonpost|bbc\.|cnn\.|reuters|bloomberg|statnews|fiercebiotech|nature\.com\/news|sciencedaily|theguardian|forbes|wsj\.|npr\.org|webmd\.com\/news)/.test(host)
  ) return 'news';
  if (
    /(harvard\.edu|stanford\.edu|mayoclinic|clevelandclinic|hopkinsmedicine|nejm\.org|thelancet|bmj\.com|cochrane|pubmed|nih\.gov|nature\.com|science\.org|cell\.com|lancet|medscape|uptodate|aafp\.org|acr\.org)/.test(host)
    || /\.edu(\.|$)/.test(host)
  ) return 'medical';
  if (/(clinic|regen|stem.?cell|orthop|sports.?med|wellness|aesthetic)/.test(host)) return 'clinic';
  return 'clinic';
}

function enrichWebResult(r) {
  const url = r.url || null;
  const source = r.source || hostnameOf(url);
  return {
    ...r,
    source,
    kind: r.kind || classifyWebKind(url, source),
    favicon: r.favicon || faviconFor(url, source),
    thumbnail: r.thumbnail || null,
  };
}

async function searchBrave(q, count) {
  const key = process.env.BRAVE_SEARCH_API_KEY;
  if (!key) return null;
  const params = new URLSearchParams({ q, count: String(count) });
  const upstream = await fetch(`https://api.search.brave.com/res/v1/web/search?${params}`, {
    headers: { Accept: 'application/json', 'X-Subscription-Token': key },
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`Brave search HTTP ${upstream.status}`);
  const data = await upstream.json();
  const results = (data.web?.results || []).map((r) => enrichWebResult({
    title: r.title || 'Untitled',
    url: r.url || null,
    snippet: r.description || '',
    source: (() => { try { return new URL(r.url).hostname.replace(/^www\./, ''); } catch { return null; } })(),
    thumbnail: r.thumbnail?.src || r.thumbnail?.url || null,
    favicon: r.meta_url?.favicon || null,
  }));
  return { provider: 'brave', results };
}

async function searchSerper(q, count) {
  const key = process.env.SERPER_API_KEY;
  if (!key) return null;
  const upstream = await fetch('https://google.serper.dev/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-KEY': key },
    body: JSON.stringify({ q, num: count }),
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`Serper HTTP ${upstream.status}`);
  const data = await upstream.json();
  const results = (data.organic || []).map((r) => enrichWebResult({
    title: r.title || 'Untitled',
    url: r.link || null,
    snippet: r.snippet || '',
    source: (() => { try { return new URL(r.link).hostname.replace(/^www\./, ''); } catch { return null; } })(),
    thumbnail: r.imageUrl || null,
  }));
  return { provider: 'serper', results };
}

/** Zero-config fallback when Brave/Serper keys are absent. */
async function searchDuckDuckGo(q, count) {
  const params = new URLSearchParams({ q });
  const upstream = await fetch(`https://html.duckduckgo.com/html/?${params}`, {
    headers: {
      Accept: 'text/html',
      'User-Agent': 'rrsrch-web-search/1.0 (+https://rrsrch.com)',
    },
    signal: AbortSignal.timeout(20000),
    redirect: 'follow',
  });
  if (!upstream.ok) throw new Error(`DuckDuckGo HTTP ${upstream.status}`);
  const html = await upstream.text();
  const results = [];
  // result__a links; uddg= is the real destination when present
  const linkRe = /class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  const snippetRe = /class="result__snippet"[^>]*>([\s\S]*?)<\/(?:a|td|div)>/gi;
  const snippets = [];
  let sm;
  while ((sm = snippetRe.exec(html)) !== null) {
    snippets.push(sm[1].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim());
  }
  let m;
  let i = 0;
  while ((m = linkRe.exec(html)) !== null && results.length < count) {
    let href = m[1].replace(/&amp;/g, '&');
    try {
      const u = new URL(href, 'https://duckduckgo.com');
      if (u.searchParams.get('uddg')) href = u.searchParams.get('uddg');
    } catch { /* keep href */ }
    if (!href || href.startsWith('/') || href.includes('duckduckgo.com')) continue;
    const title = m[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim() || 'Untitled';
    let source = null;
    try { source = new URL(href).hostname.replace(/^www\./, ''); } catch { /* ignore */ }
    results.push(enrichWebResult({
      title,
      url: href,
      snippet: snippets[i] || '',
      source,
    }));
    i += 1;
  }
  return { provider: 'duckduckgo', results };
}

/**
 * Heuristic "by argument" clustering for the Web tab.
 * Clusters snippets into claim themes and assigns yes/no sides by polarity.
 * Ledger verdict/note come from the optional client-provided report summary.
 */
function buildWebArguments(query, results = [], ledger = {}) {
  const themes = [
    {
      id: 'pain-benefit',
      title: 'MSCs lower knee pain versus control',
      match: /pain|vas|analges/i,
      yes: /lower|reduc|improv|relie|benefit|effective|significant/i,
      no: /no (significant )?difference|not (superior|better)|failed|no benefit|unclear|inconclusive/i,
      defaultVerdict: 'benefit',
      defaultNote: 'Pain outcomes favour MSCs in several trials; effect sizes vary.',
    },
    {
      id: 'function',
      title: 'MSCs improve knee function, not just pain',
      match: /function|womac|ikdc|koos|mobility|stiff/i,
      yes: /improv|better|increas|restor|gain/i,
      no: /no (significant )?difference|did not|fail|unclear|mixed|not follow/i,
      defaultVerdict: 'contested',
      defaultNote: 'Function is less consistent than pain across the ledger.',
    },
    {
      id: 'durability',
      title: 'Any benefit lasts beyond 12–24 months',
      match: /24 month|long[- ]?term|durab|sustain|lasts?/i,
      yes: /last|sustain|maintain|durable|at 24/i,
      no: /stop at 12|short[- ]?term|unclear|unknown|no data|not followed/i,
      defaultVerdict: 'uncertain',
      defaultNote: 'Most included trials stop at 12 months; longer follow-up is thin.',
    },
    {
      id: 'vs-standard',
      title: 'MSCs beat hyaluronic acid or placebo',
      match: /hyaluronic|placebo|saline|control|compar/i,
      yes: /better than|superior|outperform|favou?rs? msc/i,
      no: /no better|equivalent|similar to|not superior/i,
      defaultVerdict: 'mixed',
      defaultNote: 'Comparators matter: HA and placebo are harder bars than usual care.',
    },
    {
      id: 'safety',
      title: 'MSC injections are safe for knee OA',
      match: /safe|adverse|side effect|complicat|risk/i,
      yes: /safe|well[- ]tolerat|no serious|low risk/i,
      no: /adverse|risk|complicat|infection|caution/i,
      defaultVerdict: 'mixed',
      defaultNote: 'Serious events look uncommon in trials; reporting quality varies.',
    },
  ];

  const ledgerVerdict = ledger.verdict || null;
  const ledgerNote = ledger.note || null;
  const args = [];

  for (const theme of themes) {
    const yes = [];
    const no = [];
    for (const r of results) {
      const blob = `${r.title || ''} ${r.snippet || ''}`;
      if (!theme.match.test(blob)) continue;
      const quote = String(r.snippet || r.title || '').replace(/\s+/g, ' ').trim().slice(0, 220);
      const entry = {
        url: r.url,
        quote: quote || (r.title || ''),
        title: r.title,
        source: r.source,
        kind: r.kind,
        favicon: r.favicon,
        thumbnail: r.thumbnail,
      };
      const yesHit = theme.yes.test(blob);
      const noHit = theme.no.test(blob);
      if (yesHit && !noHit) yes.push(entry);
      else if (noHit && !yesHit) no.push(entry);
      else if (yesHit && noHit) {
        // Mixed language on the page — put with pushback if "no" wins the end of the snippet
        if (/however|but|although|despite/i.test(blob)) no.push(entry);
        else yes.push(entry);
      } else {
        // Matched theme keywords only — lean yes for clinic/news, no for authority hedging
        if (r.kind === 'authority' || r.kind === 'medical') no.push(entry);
        else yes.push(entry);
      }
    }
    if (!yes.length && !no.length) continue;
    let verdict = theme.defaultVerdict;
    let note = theme.defaultNote;
    if (ledgerVerdict && /pain|function|mixed/i.test(theme.id + theme.title)) {
      // Prefer live ledger summary when present
      if (theme.id === 'pain-benefit' && (ledgerVerdict === 'benefit' || ledgerVerdict === 'mixed')) {
        verdict = ledgerVerdict === 'mixed' ? 'benefit' : ledgerVerdict;
      }
      if (theme.id === 'function' && (ledgerVerdict === 'contested' || ledgerVerdict === 'mixed' || ledgerVerdict === 'no_difference')) {
        verdict = ledgerVerdict === 'mixed' ? 'contested' : ledgerVerdict;
      }
      if (ledgerNote && (theme.id === 'pain-benefit' || theme.id === 'function')) {
        note = ledgerNote;
      }
    }
    if (!yes.length && !no.length) continue;
    args.push({
      id: theme.id,
      title: theme.title,
      ledger: {
        verdict: verdict || 'none',
        note: note || 'Not covered by the claim ledger yet.',
      },
      yes,
      no,
    });
  }

  // If nothing matched, fall back to a single "open web claims" bucket
  if (!args.length && results.length) {
    args.push({
      id: 'general',
      title: String(query || 'What the open web claims').slice(0, 120),
      ledger: {
        verdict: ledgerVerdict || 'none',
        note: ledgerNote || 'Not covered by the claim ledger yet.',
      },
      yes: results.slice(0, 4).map((r) => ({
        url: r.url,
        quote: String(r.snippet || r.title || '').slice(0, 220),
        title: r.title,
        source: r.source,
        kind: r.kind,
        favicon: r.favicon,
        thumbnail: r.thumbnail,
      })),
      no: results.slice(4, 8).map((r) => ({
        url: r.url,
        quote: String(r.snippet || r.title || '').slice(0, 220),
        title: r.title,
        source: r.source,
        kind: r.kind,
        favicon: r.favicon,
        thumbnail: r.thumbnail,
      })),
    });
  }

  return args.slice(0, 6);
}

app.get('/api/web/search', async (req, res) => {
  const q = String(req.query.q || '').trim();
  if (!q) return res.status(400).json({ error: 'query required' });
  if (q.length > 500) return res.status(400).json({ error: 'query too long (500 characters max)' });
  const count = Math.min(Math.max(parseInt(req.query.limit, 10) || 8, 1), 20);
  try {
    let packed = null;
    let lastErr = null;
    for (const fn of [searchBrave, searchSerper, searchDuckDuckGo]) {
      try {
        packed = await fn(q, count);
        if (packed) break;
      } catch (err) {
        lastErr = err;
        console.error('web search provider failed', err.message || err);
      }
    }
    if (!packed) {
      return res.status(503).json({
        error: 'open web search unavailable',
        detail: lastErr
          ? String(lastErr.message || lastErr)
          : 'Set BRAVE_SEARCH_API_KEY or SERPER_API_KEY for reliable results.',
        configured: !!(process.env.BRAVE_SEARCH_API_KEY || process.env.SERPER_API_KEY),
      });
    }
    return res.json({
      query: q,
      provider: packed.provider,
      results: (packed.results || []).map(enrichWebResult),
      note: 'Open web — not gated ledger evidence. Research tool only, not medical advice.',
    });
  } catch (err) {
    console.error('web search failed', err);
    return res.status(500).json({ error: 'search failed' });
  }
});

/** Cluster open-web results by argument for the Web tab "By argument" view. */
app.post('/api/web/arguments', async (req, res) => {
  try {
    const body = req.body || {};
    const q = String(body.query || body.q || '').trim();
    const results = Array.isArray(body.results) ? body.results : [];
    if (!results.length) {
      return res.status(400).json({ error: 'results required' });
    }
    const ledger = body.ledger && typeof body.ledger === 'object' ? body.ledger : {};
    const enriched = results.map(enrichWebResult);
    const arguments_ = buildWebArguments(q, enriched, ledger);
    return res.json({
      query: q,
      arguments: arguments_,
      note: 'Heuristic clustering from titles/snippets — not a full page read.',
    });
  } catch (err) {
    console.error('web arguments failed', err);
    return res.status(500).json({ error: 'arguments failed' });
  }
});

/** Suggested deeper / adjacent searches (Claude-style routes of thought). */
function buildFollowUps(query, history = [], profile = {}) {
  const q = String(query || '').trim();
  const lower = q.toLowerCase();
  const prior = (history || []).map((h) => String(h || '').toLowerCase()).filter(Boolean);
  const interest = String(profile.interest || profile.focus || '').toLowerCase();
  const seen = new Set([lower, ...prior]);
  const out = [];

  const push = (item) => {
    const text = String(item.q || '').trim();
    if (!text || seen.has(text.toLowerCase())) return;
    seen.add(text.toLowerCase());
    out.push({
      id: item.id || `fu-${out.length + 1}`,
      q: text,
      why: item.why || 'Deeper angle',
      kind: item.kind || 'deeper',
      v: item.v || null,
      claims: item.claims != null ? item.claims : null,
      answer: item.answer || null,
    });
  };

  const isMsc = /msc|mesenchymal|stem cell/i.test(q);
  const isKnee = /knee|osteoarthritis|oa\b|womac|ikdc/i.test(q);
  const mentionsPain = /pain|vas/i.test(q);
  const mentionsFunction = /function|womac|ikdc|koos/i.test(q);
  const mentionsTime = /6 month|12 month|24 month|long[- ]?term|durab/i.test(q);
  const mentionsCompare = /vs\.?|versus|compar|better than|hyaluronic|placebo|prp/i.test(q);

  if (isMsc && isKnee) {
    if (!mentionsPain) {
      push({
        id: 'pain-effect',
        kind: 'benefit',
        why: 'Highest-signal clinical outcome',
        v: 'benefit',
        claims: 11,
        answer: 'Yes. Every pooled 6-month pain estimate favours MSCs.',
        q: 'Is knee pain lower with MSCs than with control at 6 months?',
      });
    }
    if (!mentionsFunction) {
      push({
        id: 'function-gap',
        kind: 'conflict',
        why: 'Where trials often disagree',
        v: 'contested',
        claims: 12,
        answer: 'Studies disagree. Function improves less consistently than pain.',
        q: 'Do MSCs improve knee function at 12 months compared with control?',
      });
    }
    if (!mentionsCompare) {
      push({
        id: 'vs-ha',
        kind: 'compare',
        why: 'Common clinical alternative',
        v: 'benefit',
        claims: 9,
        answer: 'Probably, for pain: about 1.5 to 2 points lower on a 10-point scale at 12 months.',
        q: 'Are MSCs better than hyaluronic acid for knee osteoarthritis?',
      });
      push({
        id: 'vs-placebo',
        kind: 'compare',
        why: 'Hardest control to beat',
        v: 'mixed',
        claims: 7,
        answer: 'Pain slightly lower (about 1 of 10 points), WOMAC no different.',
        q: 'How do MSCs compare with placebo injection for knee OA?',
      });
    }
    if (!mentionsTime) {
      push({
        id: 'durability',
        kind: 'gap',
        why: 'What usually isn\'t answered',
        v: 'uncertain',
        claims: 3,
        answer: 'Unclear. Most trials stop at 12 months.',
        q: 'Does the benefit of MSC injection last to 24 months?',
      });
    }
    push({
      id: 'womac-12m',
      kind: 'conflict',
      why: 'Where totals conflict',
      v: 'contested',
      claims: 10,
      answer: 'Studies disagree: three found better totals, three found no difference.',
      q: 'Is the total WOMAC score better with MSCs than with control at 12 months?',
    });
    push({
      id: 'dose-source',
      kind: 'mechanism',
      why: 'Protocol detail that changes results',
      v: 'uncertain',
      claims: 4,
      answer: 'Dose and cell source vary widely; the ledger does not yet settle which protocol wins.',
      q: 'Does MSC dose or cell source (bone marrow vs adipose) change outcomes in knee OA?',
    });
    push({
      id: 'safety',
      kind: 'safety',
      why: 'Decision-critical',
      v: 'mixed',
      claims: 6,
      answer: 'Serious adverse events are uncommon in the included trials; reporting quality varies.',
      q: 'What adverse events are reported after MSC injection for knee osteoarthritis?',
    });
  }

  // Generic intrigue routes from the query itself
  push({
    id: 'contradict',
    kind: 'conflict',
    why: 'Find the disagreement',
    q: `Where do studies disagree about: ${q}?`,
  });
  push({
    id: 'strongest',
    kind: 'evidence',
    why: 'Quality filter',
    q: `What is the strongest randomized evidence on: ${q}?`,
  });
  push({
    id: 'limits',
    kind: 'gap',
    why: 'Know what is missing',
    q: `What remains unproven about: ${q}?`,
  });

  if (interest.includes('clinic') || interest.includes('patient')) {
    push({
      id: 'practice',
      kind: 'practice',
      why: 'Matches your focus',
      q: `What would a cautious clinician tell a patient about: ${q}?`,
    });
  }
  if (interest.includes('invest') || interest.includes('market')) {
    push({
      id: 'market',
      kind: 'market',
      why: 'Matches your focus',
      q: `What commercial or trial pipeline signals matter for: ${q}?`,
    });
  }

  // Prefer questions not already asked; cap at 6
  return out.slice(0, 6);
}

app.post('/api/search/followups', async (req, res) => {
  try {
    const body = req.body || {};
    const q = String(body.query || body.q || '').trim();
    if (!q) return res.status(400).json({ error: 'query required' });
    const history = Array.isArray(body.history) ? body.history.slice(0, 20) : [];
    const profile = body.profile && typeof body.profile === 'object' ? body.profile : {};
    const suggestions = buildFollowUps(q, history, profile);
    return res.json({ query: q, suggestions });
  } catch (err) {
    console.error('followups failed', err);
    return res.status(500).json({ error: 'followups failed' });
  }
});

function clipAbstract(text, max = 2400) {
  const s = String(text || '').trim();
  if (!s) return '';
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

function normalizeDoi(doi) {
  if (!doi) return null;
  return String(doi).replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').trim().toLowerCase() || null;
}

function paperKey(p) {
  if (p.doi) return `doi:${normalizeDoi(p.doi)}`;
  if (p.pmid) return `pmid:${p.pmid}`;
  if (p.nctId) return `nct:${String(p.nctId).toUpperCase()}`;
  const t = String(p.title || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  return t ? `title:${t.slice(0, 120)}` : null;
}

function classifyStudyType(paper) {
  if (paper.kind === 'trial' || paper.nctId) return 'trial';
  const types = (paper.pubTypes || []).map((t) => String(t).toLowerCase());
  const title = String(paper.title || '');
  if (
    types.some((t) => /systematic.?review|meta.?analysis|review/.test(t))
    || /meta-?analysis|systematic review|umbrella review|network meta/i.test(title)
  ) return 'review';
  if (
    types.some((t) => /randomi[sz]ed|clinical trial|controlled trial/.test(t))
    || /randomi[sz]ed|placebo-controlled|\bRCT\b/i.test(title)
  ) return 'rct';
  return 'other';
}

/** Corpus PMIDs from the evidence-engine manifest (in-ledger papers). */
function loadCorpusPmidSet() {
  try {
    const path = require('path');
    const fs = require('fs');
    const file = path.join(__dirname, 'engine', 'corpus', 'manifest.yaml');
    const text = fs.readFileSync(file, 'utf8');
    const set = new Set();
    for (const m of text.matchAll(/^- id: (?:MED:)?(\d+)/gm)) set.add(m[1]);
    for (const m of text.matchAll(/^\s*- pmid: ['"]?(\d+)/gm)) set.add(m[1]);
    return set;
  } catch (err) {
    console.warn('corpus manifest not loaded', err.message || err);
    return new Set();
  }
}
const CORPUS_PMIDS = loadCorpusPmidSet();

/** Deterministic placeholder claim split until live engine claim counts are wired. */
function ledgerForPaper(pmid) {
  const id = String(pmid || '').replace(/^MED:/, '');
  if (!id || !CORPUS_PMIDS.has(id)) return null;
  let h = 0;
  for (let i = 0; i < id.length; i += 1) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  const benefit = 1 + (h % 3);
  const noDiff = h % 2;
  const contested = (h >> 3) % 2;
  const findings = benefit + noDiff + contested;
  const byVerdict = {};
  if (benefit) byVerdict.benefit = benefit;
  if (noDiff) byVerdict.no_difference = noDiff;
  if (contested) byVerdict.contested = contested;
  return { findings, byVerdict };
}

const LIT_SOURCE_HOST = {
  'Europe PMC': 'europepmc.org',
  OpenAlex: 'openalex.org',
  'Semantic Scholar': 'semanticscholar.org',
  'ClinicalTrials.gov': 'clinicaltrials.gov',
};

const LIT_REDIRECTOR_HOST = /^(doi\.org|dx\.doi\.org|europepmc\.org|ncbi\.nlm\.nih\.gov|pubmed\.ncbi\.nlm\.nih\.gov|semanticscholar\.org|openalex\.org|api\.semanticscholar\.org|clinicaltrials\.gov)$/i;

/** Common publishers → site host for logos when OpenAlex omits homepage_url. */
const LIT_PUBLISHER_HOST = [
  [/mdpi|multidisciplinary digital publishing/i, 'mdpi.com'],
  [/wiley/i, 'wiley.com'],
  [/elsevier|sciencedirect/i, 'sciencedirect.com'],
  [/springer|bmc|biomed central/i, 'springer.com'],
  [/nature portfolio|^nature$/i, 'nature.com'],
  [/frontiers/i, 'frontiersin.org'],
  [/\bplos\b/i, 'plos.org'],
  [/sage/i, 'sagepub.com'],
  [/oxford|oup/i, 'oup.com'],
  [/taylor|informa/i, 'tandfonline.com'],
  [/wolters kluwer|lippincott|\blww\b/i, 'lww.com'],
  [/cell press|^cell$/i, 'cell.com'],
  [/\bbmj\b/i, 'bmj.com'],
  [/lancet/i, 'thelancet.com'],
  [/\bnejm\b|new england journal/i, 'nejm.org'],
  [/karger/i, 'karger.com'],
  [/thieme/i, 'thieme-connect.com'],
  [/ieee/i, 'ieee.org'],
  [/\bacs\b|american chemical/i, 'acs.org'],
  [/hindawi/i, 'hindawi.com'],
  [/de gruyter/i, 'degruyter.com'],
  [/cambridge univ/i, 'cambridge.org'],
];

function litLogoForHost(host) {
  if (!host) return null;
  const h = String(host).replace(/^www\./, '').toLowerCase();
  if (!h || LIT_REDIRECTOR_HOST.test(h)) return null;
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(h)}&sz=128`;
}

function litSourceHost(sourceLabel) {
  const label = String(sourceLabel || '').split('·')[0].trim();
  return LIT_SOURCE_HOST[label] || null;
}

function litHostFromPublisherName(name) {
  if (!name) return null;
  for (const [re, host] of LIT_PUBLISHER_HOST) {
    if (re.test(name)) return host;
  }
  return null;
}

function litHostFromUrl(url) {
  const host = hostnameOf(url);
  if (!host || LIT_REDIRECTOR_HOST.test(host)) return null;
  return host;
}

function enrichLiteraturePaper(r) {
  const studyType = r.studyType || classifyStudyType(r);
  const ledger = r.ledger != null ? r.ledger : ledgerForPaper(r.pmid);
  let image = r.image || null;
  if (!image) {
    const host = r.publisherHost
      || litHostFromUrl(r.publisherUrl)
      || litHostFromPublisherName(r.publisher)
      || litHostFromUrl(r.oaUrl)
      || litHostFromUrl(r.url);
    image = litLogoForHost(host);
  }
  // Fall back to the literature source site logo (Europe PMC, OpenAlex, …)
  if (!image) {
    const primary = (r.sources && r.sources[0]) || String(r.source || '').split('·')[0].trim();
    const sourceHost = litSourceHost(primary);
    if (sourceHost) {
      image = `https://www.google.com/s2/favicons?domain=${encodeURIComponent(sourceHost)}&sz=128`;
    }
  }
  return { ...r, studyType, ledger, image };
}

async function searchEuropePmc(q, pageSize) {
  const params = new URLSearchParams({
    query: q,
    format: 'json',
    pageSize: String(pageSize),
    resultType: 'core',
  });
  const upstream = await fetch(`${EUROPE_PMC_SEARCH}?${params}`, {
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`Europe PMC HTTP ${upstream.status}`);
  const data = await upstream.json();
  const raw = data.resultList?.result || [];
  const hitCount = parseInt(data.hitCount, 10) || raw.length;
  const results = raw.map((r) => {
    const pmcid = r.pmcid ? String(r.pmcid).replace(/^PMC/i, '') : null;
    let url = null;
    if (r.pmid) url = `https://europepmc.org/article/MED/${r.pmid}`;
    else if (pmcid) url = `https://europepmc.org/article/PMC/${pmcid}`;
    else if (r.doi) url = `https://doi.org/${r.doi}`;
    const pubTypes = [];
    const pt = r.pubTypeList?.pubType;
    if (Array.isArray(pt)) pubTypes.push(...pt);
    else if (pt) pubTypes.push(pt);
    return {
      source: 'Europe PMC',
      kind: 'paper',
      pmid: r.pmid || null,
      pmcid: pmcid ? `PMC${pmcid}` : null,
      doi: r.doi || null,
      title: r.title || 'Untitled',
      authors: r.authorString || null,
      journal: r.journalTitle || null,
      year: r.pubYear || null,
      abstract: clipAbstract(r.abstractText),
      openAccess: r.isOpenAccess === 'Y',
      url,
      citations: null,
      pubTypes,
    };
  });
  return { source: 'Europe PMC', hitCount, results };
}

async function searchOpenAlex(q, pageSize) {
  const params = new URLSearchParams({
    search: q,
    per_page: String(pageSize),
    mailto: process.env.OPENALEX_MAILTO || 'research@rrsrch.com',
  });
  const upstream = await fetch(`https://api.openalex.org/works?${params}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`OpenAlex HTTP ${upstream.status}`);
  const data = await upstream.json();
  const raw = data.results || [];
  const results = raw.map((w) => {
    const doi = normalizeDoi(w.doi);
    const authors = (w.authorships || [])
      .map((a) => a.author?.display_name)
      .filter(Boolean)
      .slice(0, 8)
      .join(', ');
    const abstract = w.abstract_inverted_index
      ? (() => {
          // Reconstruct from inverted index
          const pairs = [];
          for (const [word, positions] of Object.entries(w.abstract_inverted_index)) {
            for (const pos of positions) pairs.push([pos, word]);
          }
          pairs.sort((a, b) => a[0] - b[0]);
          return pairs.map((p) => p[1]).join(' ');
        })()
      : '';
    const type = String(w.type || '').toLowerCase();
    const pubTypes = type ? [type.replace(/^https?:\/\/openalex\.org\//, '')] : [];
    const src = w.primary_location?.source || {};
    const publisher = src.host_organization_name || src.display_name || null;
    const publisherUrl = src.homepage_url || null;
    const oaUrl = w.open_access?.oa_url || w.best_oa_location?.pdf_url || null;
    const landing = w.primary_location?.landing_page_url || null;
    const publisherHost = litHostFromUrl(publisherUrl)
      || litHostFromPublisherName(publisher)
      || litHostFromUrl(oaUrl)
      || litHostFromUrl(landing);
    return {
      source: 'OpenAlex',
      kind: 'paper',
      pmid: null,
      pmcid: null,
      doi,
      title: w.display_name || w.title || 'Untitled',
      authors: authors || null,
      journal: src.display_name || null,
      year: w.publication_year ? String(w.publication_year) : null,
      abstract: clipAbstract(abstract),
      openAccess: !!w.open_access?.is_oa,
      url: landing || (doi ? `https://doi.org/${doi}` : w.id) || null,
      citations: typeof w.cited_by_count === 'number' ? w.cited_by_count : null,
      pubTypes,
      publisher,
      publisherUrl,
      publisherHost,
      oaUrl,
    };
  });
  return {
    source: 'OpenAlex',
    hitCount: data.meta?.count ?? results.length,
    results,
  };
}

async function searchSemanticScholar(q, pageSize) {
  const params = new URLSearchParams({
    query: q,
    limit: String(pageSize),
    fields: 'title,abstract,year,authors,venue,externalIds,url,citationCount,openAccessPdf',
  });
  const headers = { Accept: 'application/json' };
  if (process.env.SEMANTIC_SCHOLAR_API_KEY) {
    headers['x-api-key'] = process.env.SEMANTIC_SCHOLAR_API_KEY;
  }
  const upstream = await fetch(`https://api.semanticscholar.org/graph/v1/paper/search?${params}`, {
    headers,
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`Semantic Scholar HTTP ${upstream.status}`);
  const data = await upstream.json();
  const raw = data.data || [];
  const results = raw.map((p) => {
    const doi = normalizeDoi(p.externalIds?.DOI);
    const pmid = p.externalIds?.PubMed || null;
    const authors = (p.authors || []).map((a) => a.name).filter(Boolean).slice(0, 8).join(', ');
    return {
      source: 'Semantic Scholar',
      kind: 'paper',
      pmid,
      pmcid: p.externalIds?.PubMedCentral ? `PMC${p.externalIds.PubMedCentral}` : null,
      doi,
      title: p.title || 'Untitled',
      authors: authors || null,
      journal: p.venue || null,
      year: p.year ? String(p.year) : null,
      abstract: clipAbstract(p.abstract),
      openAccess: !!p.openAccessPdf?.url,
      url: p.url || p.openAccessPdf?.url || (doi ? `https://doi.org/${doi}` : null),
      citations: typeof p.citationCount === 'number' ? p.citationCount : null,
    };
  });
  return {
    source: 'Semantic Scholar',
    hitCount: data.total ?? results.length,
    results,
  };
}

async function searchClinicalTrials(q, pageSize) {
  const params = new URLSearchParams({
    'query.term': q,
    pageSize: String(Math.min(pageSize, 10)),
    format: 'json',
    fields: 'NCTId,BriefTitle,OfficialTitle,OverallStatus,Phase,StartDate,Condition,InterventionName,BriefSummary',
  });
  const upstream = await fetch(`https://clinicaltrials.gov/api/v2/studies?${params}`, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(20000),
  });
  if (!upstream.ok) throw new Error(`ClinicalTrials.gov HTTP ${upstream.status}`);
  const data = await upstream.json();
  const raw = data.studies || [];
  const results = raw.map((s) => {
    const proto = s.protocolSection || {};
    const id = proto.identificationModule || {};
    const status = proto.statusModule || {};
    const design = proto.designModule || {};
    const cond = proto.conditionsModule || {};
    const inter = proto.armsInterventionsModule || {};
    const desc = proto.descriptionModule || {};
    const nctId = id.nctId || null;
    const phases = (design.phases || []).join(', ');
    const interventions = (inter.interventions || [])
      .map((i) => i.name)
      .filter(Boolean)
      .slice(0, 4)
      .join(', ');
    return {
      source: 'ClinicalTrials.gov',
      kind: 'trial',
      pmid: null,
      pmcid: null,
      doi: null,
      nctId,
      title: id.briefTitle || id.officialTitle || 'Untitled trial',
      authors: null,
      journal: [status.overallStatus, phases].filter(Boolean).join(' · ') || 'Clinical trial',
      year: (status.startDateStruct?.date || status.startDate || '').slice(0, 4) || null,
      abstract: clipAbstract([
        desc.briefSummary,
        cond.conditions?.length ? `Conditions: ${cond.conditions.join(', ')}` : null,
        interventions ? `Interventions: ${interventions}` : null,
      ].filter(Boolean).join('\n\n')),
      openAccess: true,
      url: nctId ? `https://clinicaltrials.gov/study/${nctId}` : null,
      citations: null,
    };
  });
  return {
    source: 'ClinicalTrials.gov',
    hitCount: data.totalCount ?? results.length,
    results,
  };
}

function mergeLiteratureResults(packs, limit) {
  const byKey = new Map();
  const sourceHits = {};
  const used = [];
  for (const pack of packs) {
    if (!pack) continue;
    sourceHits[pack.source] = pack.hitCount ?? pack.results?.length ?? 0;
    used.push(pack.source);
    for (const r of pack.results || []) {
      const key = paperKey(r);
      if (!key) continue;
      const existing = byKey.get(key);
      if (!existing) {
        byKey.set(key, { ...r, sources: [r.source] });
        continue;
      }
      // Prefer richer abstract / OA / citation counts; keep multi-source label
      if (!existing.sources.includes(r.source)) existing.sources.push(r.source);
      if ((!existing.abstract || existing.abstract.length < 80) && r.abstract) {
        existing.abstract = r.abstract;
      }
      if (!existing.url && r.url) existing.url = r.url;
      if (!existing.doi && r.doi) existing.doi = r.doi;
      if (!existing.pmid && r.pmid) existing.pmid = r.pmid;
      if (!existing.openAccess && r.openAccess) existing.openAccess = true;
      if ((existing.citations == null) && r.citations != null) existing.citations = r.citations;
      if (!existing.authors && r.authors) existing.authors = r.authors;
      if (!existing.journal && r.journal) existing.journal = r.journal;
      if ((!existing.pubTypes || !existing.pubTypes.length) && r.pubTypes?.length) {
        existing.pubTypes = r.pubTypes;
      } else if (existing.pubTypes && r.pubTypes?.length) {
        existing.pubTypes = [...new Set([...existing.pubTypes, ...r.pubTypes])];
      }
      if (!existing.publisherHost && r.publisherHost) existing.publisherHost = r.publisherHost;
      if (!existing.publisherUrl && r.publisherUrl) existing.publisherUrl = r.publisherUrl;
      if (!existing.publisher && r.publisher) existing.publisher = r.publisher;
      if (!existing.oaUrl && r.oaUrl) existing.oaUrl = r.oaUrl;
    }
  }
  const rankPaper = (a, b) => {
    const ca = a.citations ?? -1;
    const cb = b.citations ?? -1;
    if (cb !== ca) return cb - ca;
    const ya = parseInt(a.year, 10) || 0;
    const yb = parseInt(b.year, 10) || 0;
    return yb - ya;
  };
  const all = Array.from(byKey.values());
  const trials = all.filter((r) => r.kind === 'trial' || r.nctId).sort(rankPaper);
  const papers = all.filter((r) => !(r.kind === 'trial' || r.nctId)).sort(rankPaper);
  // Keep room for registered trials so the Literature tab can group them
  const trialSlots = Math.min(trials.length, Math.max(2, Math.min(4, Math.floor(limit / 4))));
  const paperSlots = Math.max(0, limit - trialSlots);
  const picked = [...papers.slice(0, paperSlots), ...trials.slice(0, trialSlots)];
  const results = picked.map((r) => enrichLiteraturePaper({
    ...r,
    source: (r.sources && r.sources.length > 1) ? r.sources.join(' · ') : r.source,
  }));
  const hitCount = Object.values(sourceHits).reduce((a, b) => a + (Number(b) || 0), 0);
  return { results, hitCount, sourceHits, sources: used };
}

// Multi-source literature: Europe PMC + OpenAlex + Semantic Scholar + ClinicalTrials.gov
app.get('/api/literature/search', async (req, res) => {
  const q = String(req.query.q || '').trim();
  if (!q) {
    return res.status(400).json({ error: 'query required' });
  }
  if (q.length > 500) {
    return res.status(400).json({ error: 'query too long (500 characters max)' });
  }
  const pageSize = Math.min(Math.max(parseInt(req.query.limit, 10) || 12, 1), 25);
  const perSource = Math.min(Math.max(pageSize, 8), 15);
  try {
    const settled = await Promise.allSettled([
      searchEuropePmc(q, perSource),
      searchOpenAlex(q, perSource),
      searchSemanticScholar(q, perSource),
      searchClinicalTrials(q, Math.min(perSource, 8)),
    ]);
    const packs = [];
    const errors = {};
    for (const s of settled) {
      if (s.status === 'fulfilled') packs.push(s.value);
      else {
        const msg = String(s.reason?.message || s.reason || 'failed');
        console.error('literature source failed', msg);
        // Infer source name from error prefix when possible
        const m = msg.match(/^(Europe PMC|OpenAlex|Semantic Scholar|ClinicalTrials\.gov)/);
        errors[m ? m[1] : 'unknown'] = msg;
      }
    }
    if (!packs.length) {
      return res.status(502).json({
        error: 'literature sources unavailable',
        detail: Object.values(errors).join('; ') || 'all providers failed',
      });
    }
    const merged = mergeLiteratureResults(packs, pageSize);
    res.json({
      query: q,
      hitCount: merged.hitCount,
      results: merged.results,
      sources: merged.sources,
      sourceHits: merged.sourceHits,
      errors: Object.keys(errors).length ? errors : undefined,
      note: 'Multi-source research (papers + trials). Not gated ledger evidence.',
    });
  } catch (err) {
    console.error('literature search failed', err);
    res.status(500).json({ error: 'search failed' });
  }
});

// API endpoint to fetch market indices
app.get('/api/markets', async (req, res) => {
  try {
    // Use ETFs and proxy stocks for market data (Finnhub compatible)
    const indices = [
      { symbol: 'SPY', name: 'S&P 500' },
      { symbol: 'DIA', name: 'Dow Jones' },
      { symbol: 'QQQ', name: 'NASDAQ' },
      { symbol: 'IWM', name: 'Russell 2000' },
      { symbol: 'VXX', name: 'VIX (Volatility)' },
      { symbol: 'GLD', name: 'Gold' },
      { symbol: 'USO', name: 'Crude Oil' },
      { symbol: 'TLT', name: '10Y Treasury' }
    ];

    const API_KEY = process.env.FINNHUB_API_KEY;

    if (!API_KEY) {
      return res.status(500).json({ error: 'Finnhub API key not configured' });
    }

    const marketPromises = indices.map(async ({ symbol, name }) => {
      try {
        const quoteResponse = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${API_KEY}`);
        const quoteData = await quoteResponse.json();

        const change = quoteData.c && quoteData.pc ? ((quoteData.c - quoteData.pc) / quoteData.pc) * 100 : 0;

        return {
          symbol: name,
          name,
          price: quoteData.c || 0,
          change: change,
          previousClose: quoteData.pc || 0,
          high: quoteData.h || 0,
          low: quoteData.l || 0
        };
      } catch (err) {
        console.error(`Error fetching ${symbol}:`, err);
        return {
          symbol: name,
          name,
          price: 0,
          change: 0,
          previousClose: 0,
          high: 0,
          low: 0
        };
      }
    });

    const markets = await Promise.all(marketPromises);
    res.json({ markets });
  } catch (error) {
    console.error('Error fetching market data:', error);
    res.status(500).json({ error: 'Failed to fetch market data', details: error.message });
  }
});

// API endpoint to fetch individual stock quote from Finnhub
app.get('/api/stock/:symbol', async (req, res) => {
  try {
    const { symbol } = req.params;
    const API_KEY = process.env.FINNHUB_API_KEY;

    if (!API_KEY) {
      return res.status(500).json({ error: 'Finnhub API key not configured' });
    }

    const quoteResponse = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol.toUpperCase()}&token=${API_KEY}`);
    const quoteData = await quoteResponse.json();

    // Calculate change percentage
    const change = quoteData.c && quoteData.pc ? ((quoteData.c - quoteData.pc) / quoteData.pc) * 100 : 0;

    res.json({
      symbol,
      price: quoteData.c || 0,
      change: change,
      previousClose: quoteData.pc || 0,
      high: quoteData.h || 0,
      low: quoteData.l || 0
    });
  } catch (error) {
    console.error('Error fetching stock quote:', error);
    res.status(500).json({ error: 'Failed to fetch stock quote', details: error.message });
  }
});

// API endpoint to fetch stock quotes from Finnhub
app.get('/api/stocks', async (req, res) => {
  try {
    // All stocks from all presets (AI & Chips, Robotics, Defense, Energy & Power)
    const stockSymbols = [
      // AI & Chips
      'NVDA', 'AMD', 'AVGO', 'TSM', 'INTC', 'QCOM', 'MU', 'SNOW', 'SMCI', 'GOOGL', 'PLTR', 'CLS',
      // Robotics
      'SYM', 'KYCCF', 'ISRG', 'ZBRA', 'PATH', 'EMR', 'TRMB', 'OMCL', 'LECO', 'ABB',
      // Defense
      'LMT', 'RTX', 'NOC', 'GD', 'HWM', 'AXON', 'HII', 'KTOS', 'AVAV',
      // Energy & Power
      'NEE', 'GEV', '300274.SZ', 'FSLR', 'BE', 'ADANIGREEN.NS', 'BEP', 'VWS.CO', '916.HK', 'EDPR.LS', 'CVX', 'XOM', 'BP', 'SLRP', 'SLDP'
    ];
    const API_KEY = process.env.FINNHUB_API_KEY;

    if (!API_KEY) {
      return res.status(500).json({ error: 'Finnhub API key not configured' });
    }

    const stockPromises = stockSymbols.map(async (symbol) => {
      try {
        // Fetch current quote
        const quoteResponse = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${API_KEY}`);
        const quoteData = await quoteResponse.json();

        // Calculate 24h change percentage
        const change = quoteData.c && quoteData.pc ? ((quoteData.c - quoteData.pc) / quoteData.pc) * 100 : 0;

        return {
          symbol,
          price: quoteData.c || 0,
          change: change,
          previousClose: quoteData.pc || 0,
          high: quoteData.h || 0,
          low: quoteData.l || 0,
          volume: 0 // Finnhub free tier doesn't provide volume in quote endpoint
        };
      } catch (err) {
        console.error(`Error fetching ${symbol}:`, err);
        return {
          symbol,
          price: 0,
          change: 0,
          previousClose: 0,
          high: 0,
          low: 0,
          volume: 0
        };
      }
    });

    const stocks = await Promise.all(stockPromises);
    res.json({ stocks });
  } catch (error) {
    console.error('Error fetching stock data:', error);
    res.status(500).json({ error: 'Failed to fetch stock data', details: error.message });
  }
});

// API endpoint to fetch AI ETFs from Finnhub
app.get('/api/etfs', async (req, res) => {
  try {
    // Top AI-focused ETFs
    const etfSymbols = [
      'BOTZ',  // Global X Robotics & AI ETF
      'ROBT',  // First Trust Nasdaq AI & Robotics ETF
      'IRBO',  // iShares Robotics and AI Multisector ETF
      'ARKQ',  // ARK Autonomous Tech & Robotics ETF
      'THNQ',  // ROBO Global AI ETF
      'AIQ',   // Global X AI & Technology ETF
      'WTAI',  // WisdomTree AI Enhanced Value Fund
      'AIEQ',  // AI Powered Equity ETF
      'LRNZ',  // TrueShares Tech, AI & Deep Learning ETF
      'BIGZ'   // Roundhill Generative AI & Technology ETF
    ];

    const API_KEY = process.env.FINNHUB_API_KEY;

    if (!API_KEY) {
      return res.status(500).json({ error: 'Finnhub API key not configured' });
    }

    const etfPromises = etfSymbols.map(async (symbol) => {
      try {
        const quoteResponse = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${API_KEY}`);
        const quoteData = await quoteResponse.json();

        const change = quoteData.c && quoteData.pc ? ((quoteData.c - quoteData.pc) / quoteData.pc) * 100 : 0;

        return {
          symbol,
          price: quoteData.c || 0,
          change: change,
          previousClose: quoteData.pc || 0,
          high: quoteData.h || 0,
          low: quoteData.l || 0,
          volume: 0
        };
      } catch (err) {
        console.error(`Error fetching ${symbol}:`, err);
        return {
          symbol,
          price: 0,
          change: 0,
          previousClose: 0,
          high: 0,
          low: 0,
          volume: 0
        };
      }
    });

    const etfs = await Promise.all(etfPromises);
    res.json({ etfs });
  } catch (error) {
    console.error('Error fetching ETF data:', error);
    res.status(500).json({ error: 'Failed to fetch ETF data', details: error.message });
  }
});

// API endpoint to fetch tweets
app.get('/api/tweets', async (req, res) => {
  try {
    // First get the user ID for @rrsrch
    const user = await twitterClient.v2.userByUsername('rrsrch');

    if (!user.data) {
      return res.status(404).json({ error: 'User not found' });
    }

    // Then fetch their tweets (with full text, not truncated)
    const tweets = await twitterClient.v2.userTimeline(user.data.id, {
      max_results: 5,
      'tweet.fields': ['created_at', 'public_metrics', 'text'],
      expansions: ['author_id', 'referenced_tweets.id'],
      'user.fields': ['username', 'name'],
      exclude: 'retweets'
    });

    const formattedTweets = tweets.data.data.map(tweet => ({
      id: tweet.id,
      text: tweet.text, // Twitter API v2 returns full text by default
      created_at: tweet.created_at,
      metrics: tweet.public_metrics
    }));

    res.json({ tweets: formattedTweets });
  } catch (error) {
    console.error('Error fetching tweets:', error);
    res.status(500).json({ error: 'Failed to fetch tweets', details: error.message });
  }
});

// Get all posts
app.get('/api/posts', async (req, res) => {
  try {
    const posts = await readPosts();
    res.json({ posts: posts.sort((a, b) => new Date(b.date) - new Date(a.date)) });
  } catch (error) {
    console.error('Error reading posts:', error);
    res.status(500).json({ error: 'Failed to fetch posts' });
  }
});

// Create a new post (requires API key)
app.post('/api/posts', async (req, res) => {
  const apiKey = req.headers['x-api-key'];

  if (!apiKey || apiKey !== process.env.API_KEY) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  const { title, excerpt, content, topic } = req.body;

  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  try {
    const posts = await readPosts();

    const newPost = {
      id: Date.now().toString(),
      title,
      excerpt: excerpt || '', // Make excerpt optional for tweets/updates
      content: content || '',
      topic: topic || 'All',
      date: new Date().toISOString()
    };

    posts.push(newPost);
    await writePosts(posts);

    res.json({ success: true, post: newPost });
  } catch (error) {
    console.error('Error creating post:', error);
    res.status(500).json({ error: 'Failed to create post' });
  }
});

// Delete a post (requires API key)
app.delete('/api/posts/:id', async (req, res) => {
  const apiKey = req.headers['x-api-key'];

  if (!apiKey || apiKey !== process.env.API_KEY) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  try {
    const posts = await readPosts();
    const filteredPosts = posts.filter(p => p.id !== req.params.id);

    if (posts.length === filteredPosts.length) {
      return res.status(404).json({ error: 'Post not found' });
    }

    await writePosts(filteredPosts);
    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting post:', error);
    res.status(500).json({ error: 'Failed to delete post' });
  }
});

// Google OAuth routes
app.get('/api/auth/google', (req, res, next) => {
  if (!googleOAuthEnabled) {
    return res.status(503).json({ error: 'Google sign-in is not configured' });
  }
  passport.authenticate('google', { scope: ['profile', 'email'] })(req, res, next);
});

app.get('/api/auth/google/callback', (req, res, next) => {
  if (!googleOAuthEnabled) {
    return res.status(503).json({ error: 'Google sign-in is not configured' });
  }
  passport.authenticate('google', { failureRedirect: '/' })(req, res, () => {
    // Successful authentication, redirect to frontend with user data
    const frontendURL = process.env.FRONTEND_URL || 'http://localhost:3000';
    res.redirect(`${frontendURL}?auth=success&user=${encodeURIComponent(JSON.stringify(req.user))}`);
  });
});

// Get current user
app.get('/api/auth/user', (req, res) => {
  if (req.isAuthenticated()) {
    res.json({ user: req.user });
  } else {
    res.status(401).json({ error: 'Not authenticated' });
  }
});

// Logout
app.get('/api/auth/logout', (req, res) => {
  req.logout((err) => {
    if (err) {
      return res.status(500).json({ error: 'Logout failed' });
    }
    res.json({ success: true });
  });
});

// --- Account auth (email + password, v0) ------------------------------------
// Serverless-safe by design: no sessions (stateless HMAC tokens verified per
// request) and users persisted in Vercel Blob like posts are. Blob objects are
// public-by-URL, so the user store lives at an UNGUESSABLE pathname derived
// from AUTH_SECRET (capability URL) and holds bcrypt hashes only — never
// plaintext. v0 tradeoffs, documented: no rate limiting, last-write-wins on
// concurrent signups, and rotating SESSION_SECRET both invalidates tokens and
// moves the users blob key (migrate the blob if you rotate).
const crypto = require('crypto');

const AUTH_SECRET = process.env.SESSION_SECRET || 'rrsrch-secret-key-2025';
// Versioned writes, never overwrites: blob overwrites of the SAME pathname are
// CDN-cached (stale reads for up to ~a minute — verified live), which is fatal
// for an auth store. Every write lands at a NEW pathname under a secret prefix;
// reads list the prefix and fetch the newest version's unique URL, so
// read-after-write is consistent. Old versions are pruned best-effort.
const USERS_PREFIX = 'users-' + crypto.createHash('sha256')
  .update('rrsrch-users:' + AUTH_SECRET).digest('hex').slice(0, 40) + '/';
const USERS_FILE = path.join(__dirname, 'users.json');

async function latestUsersBlob() {
  const { list } = require('@vercel/blob');
  const { blobs } = await list({ prefix: USERS_PREFIX });
  if (!blobs.length) return null;
  // version filenames are zero-padded ms timestamps — lexicographic max = newest
  return blobs.reduce((a, b) => (a.pathname > b.pathname ? a : b));
}

/// Every failure below used to return `[]`, which reads downstream as "this account
/// store is empty" — indistinguishable from "we could not read the account store".
/// Those are opposite problems: one needs a restore, the other needs a credential.
/// Each path now says which it was, without logging the secret-derived prefix or the
/// blob URL (that path is unguessable by design and belongs in logs no more than a key
/// does). Callers still get `[]`, so behaviour is unchanged — only the silence is.
async function readUsers() {
  if (useBlob) {
    let match;
    try {
      match = await latestUsersBlob();
    } catch (err) {
      console.error(`users: blob LIST failed (${err.message}) — accounts unread, not absent`);
      return [];
    }
    if (!match) {
      console.error('users: no users blob under the expected prefix — store empty, '
                    + 'or the prefix moved with AUTH_SECRET');
      return [];
    }
    // Read through the SDK with the store token, NOT by fetching the public CDN URL.
    // The unauthenticated fetch is what started returning 403 and logged every runner
    // out: the accounts were there the whole time, refused at the edge. `useCache:
    // false` also reads from origin, so a stale or poisoned CDN entry can't do this
    // again. The account store is the wrong thing to be reading over an anonymous URL.
    // Both access modes, because the store's mode is the open question: `list`
    // authenticates and works, while a public-mode read is refused with 403. If the
    // store (or this object) is private now, only the private read carries the token
    // in a way the origin accepts. Whichever succeeds is logged, so one deploy answers
    // it instead of another round of guessing.
    let text;
    try {
      const { get } = require('@vercel/blob');
      let result = null;
      let mode = null;
      for (const access of ['private', 'public']) {
        try {
          result = await get(match.pathname, { access, useCache: false });
          if (result) { mode = access; break; }
        } catch (modeErr) {
          console.error(`users: blob GET access='${access}' failed (${modeErr.message})`);
        }
      }
      if (!result) throw new Error('both access modes refused the read');
      console.log(`users: blob GET succeeded with access='${mode}'`);
      if (result.statusCode !== 200 || !result.stream) {
        console.error(`users: blob GET status ${result.statusCode} with no body`);
        return [];
      }
      text = await new Response(result.stream).text();
    } catch (err) {
      // Keep the old path as a fallback: if the SDK read fails for a reason the
      // public URL doesn't share, an available account store beats a tidy one.
      console.error(`users: blob GET failed (${err.message}) — falling back to public URL`);
      try {
        const res = await fetch(match.url, { cache: 'no-store' });
        if (!res.ok) {
          console.error(`users: fallback FETCH ${res.status} — accounts unread, not absent`);
          return [];
        }
        text = await res.text();
      } catch (fallbackErr) {
        console.error(`users: fallback FETCH threw (${fallbackErr.message})`);
        return [];
      }
    }
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) {
        console.error(`users: blob parsed to ${typeof parsed}, expected an array`);
        return [];
      }
      return parsed;
    } catch (err) {
      console.error(`users: blob JSON parse failed (${err.message})`);
      return [];
    }
  }
  try {
    const parsed = JSON.parse(await fs.readFile(USERS_FILE, 'utf8'));
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    // On serverless this is the expected outcome of running WITHOUT a blob token: the
    // filesystem is read-only and empty, so every account silently disappears.
    console.error(`users: local file store unreadable (${err.code || err.message}) — `
                  + 'this is the fallback path; is BLOB_READ_WRITE_TOKEN set?');
    return [];
  }
}

async function writeUsers(users) {
  if (useBlob) {
    const { put, del, list } = require('@vercel/blob');
    const key = `${USERS_PREFIX}v-${String(Date.now()).padStart(16, '0')}.json`;
    await put(key, JSON.stringify(users, null, 2), {
      access: 'public',
      contentType: 'application/json',
      addRandomSuffix: false,
    });
    try {   // best-effort prune of superseded versions
      const { blobs } = await list({ prefix: USERS_PREFIX });
      const old = blobs.filter((b) => b.pathname < key).map((b) => b.url);
      if (old.length) await del(old);
    } catch (err) {
      console.error('users prune failed (harmless):', err.message);
    }
    return;
  }
  await fs.writeFile(USERS_FILE, JSON.stringify(users, null, 2));
}

const b64url = (buf) => Buffer.from(buf).toString('base64url');
function signToken(payload) {
  const body = b64url(JSON.stringify(payload));
  const mac = crypto.createHmac('sha256', AUTH_SECRET).update(body).digest('base64url');
  return `${body}.${mac}`;
}
function verifyToken(token) {
  if (!token || !token.includes('.')) return null;
  const [body, mac] = token.split('.');
  const expect = crypto.createHmac('sha256', AUTH_SECRET).update(body).digest('base64url');
  if (mac.length !== expect.length
      || !crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(expect))) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString());
    if (!payload.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}
const publicUser = (u) => ({ id: u.id, name: u.name, email: u.email, created_at: u.created_at });
const tokenFor = (u) => signToken({ sub: u.id, exp: Date.now() + 30 * 24 * 3600 * 1000 });

async function requireUser(req, res) {
  const token = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const payload = verifyToken(token);
  if (!payload) {
    // The caller never proved who they are: bad signature, malformed, or expired.
    // Their problem, and the ordinary case — logged quietly.
    console.warn('auth: token rejected (bad signature, malformed, or expired)');
    res.status(401).json({ error: 'Not authenticated', reason: 'invalid_token' });
    return null;
  }
  const users = await readUsers();
  const user = users.find((u) => u.id === payload.sub);
  if (!user) {
    // A VALID signature for an account that isn't there. Reaching this line already
    // required possession of a real token, so this is our problem, not the caller's —
    // usually the users store failing to load rather than a deleted account. The
    // count is the tell: 0 means the store came back empty, a non-zero count means
    // this one record is genuinely gone.
    console.error(
      `auth: valid token for unknown user ${payload.sub} — users loaded: ${users.length}`
    );
    res.status(401).json({ error: 'Not authenticated', reason: 'unknown_user' });
    return null;
  }
  // device tokens are revocable: the device must still be on the account
  if (payload.dev && !(user.devices || []).some((d) => d.id === payload.dev)) {
    console.warn(`auth: device ${payload.dev} not on account ${user.id}`);
    res.status(401).json({ error: 'Device revoked', reason: 'device_revoked' });
    return null;
  }
  return user;
}

app.post('/api/account/signup', async (req, res) => {
  try {
    const { name, email, password } = req.body || {};
    const cleanEmail = String(email || '').trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      return res.status(400).json({ error: 'Enter a valid email address.' });
    }
    if (!password || String(password).length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters.' });
    }
    const users = await readUsers();
    if (users.some((u) => u.email === cleanEmail)) {
      return res.status(409).json({ error: 'An account with that email already exists.' });
    }
    const user = {
      id: crypto.randomUUID(),
      name: String(name || '').trim().slice(0, 80) || cleanEmail.split('@')[0],
      email: cleanEmail,
      password_hash: await bcrypt.hash(String(password), 10),
      created_at: new Date().toISOString(),
    };
    users.push(user);
    await writeUsers(users);
    res.status(201).json({ token: tokenFor(user), user: publicUser(user) });
  } catch (err) {
    console.error('signup failed:', err);
    res.status(500).json({ error: 'Signup failed.' });
  }
});

app.post('/api/account/login', async (req, res) => {
  try {
    const cleanEmail = String((req.body || {}).email || '').trim().toLowerCase();
    const user = (await readUsers()).find((u) => u.email === cleanEmail);
    const ok = user && await bcrypt.compare(String((req.body || {}).password || ''),
                                            user.password_hash);
    if (!ok) return res.status(401).json({ error: 'Wrong email or password.' });
    res.json({ token: tokenFor(user), user: publicUser(user) });
  } catch (err) {
    console.error('login failed:', err);
    res.status(500).json({ error: 'Login failed.' });
  }
});

app.get('/api/account/me', async (req, res) => {
  const user = await requireUser(req, res);
  if (user) {
    res.json({ user: publicUser(user), devices: user.devices || [],
               projects: user.projects || [],
               active_project_id: user.active_project_id || null });
  }
});

// projects: named endpoint sets the dashboard toggles between (account-backed
// so they follow the user across browsers/machines)
app.post('/api/account/projects', async (req, res) => {
  const user = await requireUser(req, res);
  if (!user) return;
  const { projects, active_project_id } = req.body || {};
  if (!Array.isArray(projects) || projects.length === 0 || projects.length > 20) {
    return res.status(400).json({ error: 'Projects must be a list of 1-20 entries.' });
  }
  const clean = projects.map((p) => ({
    id: String(p.id || crypto.randomUUID()).slice(0, 40),
    name: String(p.name || 'untitled').slice(0, 60),
    backpack_url: String(p.backpack_url || '').slice(0, 200),
  }));
  const users = await readUsers();
  const u = users.find((x) => x.id === user.id);
  u.projects = clean;
  u.active_project_id = String(active_project_id || clean[0].id).slice(0, 40);
  await writeUsers(users);
  res.json({ projects: clean, active_project_id: u.active_project_id });
});

// self-delete (also how probe/test accounts get cleaned up)
app.delete('/api/account/me', async (req, res) => {
  const user = await requireUser(req, res);
  if (!user) return;
  const users = (await readUsers()).filter((u) => u.id !== user.id);
  await writeUsers(users);
  res.json({ deleted: true });
});

// --- Device pairing (the Claude Code-style login for local MCP instances) ----
// `rrsrch-login` on the operator's machine: start -> user approves the code in
// their signed-in dashboard -> poll returns an account-scoped device token.
// Pending codes live in a versioned blob like users; device tokens carry a
// device id and are revocable (requireUser checks the user's device list).
const PAIR_PREFIX = 'pairings-' + crypto.createHash('sha256')
  .update('rrsrch-pairings:' + AUTH_SECRET).digest('hex').slice(0, 40) + '/';
const PAIR_FILE = path.join(__dirname, 'pairings.json');
const PAIR_TTL_MS = 15 * 60 * 1000;

async function readPairings() {
  if (useBlob) {
    const { list } = require('@vercel/blob');
    const { blobs } = await list({ prefix: PAIR_PREFIX });
    if (!blobs.length) return [];
    const newest = blobs.reduce((a, b) => (a.pathname > b.pathname ? a : b));
    const res = await fetch(newest.url, { cache: 'no-store' });
    return res.ok ? res.json() : [];
  }
  try {
    return JSON.parse(await fs.readFile(PAIR_FILE, 'utf8'));
  } catch {
    return [];
  }
}

async function writePairings(pairings) {
  const live = pairings.filter((p) => p.expires_at > Date.now() - 60 * 60 * 1000);
  if (useBlob) {
    const { put, del, list } = require('@vercel/blob');
    const key = `${PAIR_PREFIX}v-${String(Date.now()).padStart(16, '0')}.json`;
    await put(key, JSON.stringify(live), {
      access: 'public', contentType: 'application/json', addRandomSuffix: false,
    });
    try {
      const { blobs } = await list({ prefix: PAIR_PREFIX });
      const old = blobs.filter((b) => b.pathname < key).map((b) => b.url);
      if (old.length) await del(old);
    } catch (err) {
      console.error('pairings prune failed (harmless):', err.message);
    }
    return;
  }
  await fs.writeFile(PAIR_FILE, JSON.stringify(live));
}

const CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';   // no 0/O/1/I/L
function userCode() {
  const pick = () => CODE_ALPHABET[crypto.randomInt(CODE_ALPHABET.length)];
  return `${pick()}${pick()}${pick()}${pick()}-${pick()}${pick()}${pick()}${pick()}`;
}
const deviceTokenFor = (u, deviceId) =>
  signToken({ sub: u.id, dev: deviceId, exp: Date.now() + 365 * 24 * 3600 * 1000 });

app.post('/api/device/start', async (req, res) => {
  try {
    const pairing = {
      user_code: userCode(),
      device_code: crypto.randomUUID(),
      device_name: String((req.body || {}).device_name || 'unnamed device').slice(0, 60),
      created_at: Date.now(),
      expires_at: Date.now() + PAIR_TTL_MS,
      approved_by: null,
      consumed: false,
    };
    const pairings = await readPairings();
    pairings.push(pairing);
    await writePairings(pairings);
    res.status(201).json({
      user_code: pairing.user_code,
      device_code: pairing.device_code,
      verification_uri: `https://rrsrch.com/#/account?pair=${pairing.user_code}`,
      expires_in: Math.floor(PAIR_TTL_MS / 1000),
      interval: 5,
    });
  } catch (err) {
    console.error('device/start failed:', err);
    res.status(500).json({ error: 'Could not start pairing.' });
  }
});

app.post('/api/device/approve', async (req, res) => {
  try {
    const user = await requireUser(req, res);
    if (!user) return;
    const code = String((req.body || {}).user_code || '').trim().toUpperCase();
    const pairings = await readPairings();
    const p = pairings.find((x) => x.user_code === code && !x.consumed);
    if (!p || p.expires_at < Date.now()) {
      return res.status(404).json({ error: 'Unknown or expired code.' });
    }
    if (p.approved_by) return res.status(409).json({ error: 'Code already approved.' });
    p.approved_by = user.id;
    p.device_id = crypto.randomUUID();
    await writePairings(pairings);
    // record the device on the account (this is also the revocation list)
    const users = await readUsers();
    const u = users.find((x) => x.id === user.id);
    u.devices = [...(u.devices || []),
      { id: p.device_id, name: p.device_name, paired_at: new Date().toISOString() }];
    await writeUsers(users);
    res.json({ approved: true, device_name: p.device_name });
  } catch (err) {
    console.error('device/approve failed:', err);
    res.status(500).json({ error: 'Approval failed.' });
  }
});

app.post('/api/device/poll', async (req, res) => {
  try {
    const dc = String((req.body || {}).device_code || '');
    const pairings = await readPairings();
    const p = pairings.find((x) => x.device_code === dc);
    if (!p || (p.expires_at < Date.now() && !p.approved_by)) {
      return res.json({ status: 'expired' });
    }
    if (!p.approved_by) return res.json({ status: 'pending' });
    if (p.consumed) return res.json({ status: 'expired' });
    p.consumed = true;
    await writePairings(pairings);
    const user = (await readUsers()).find((u) => u.id === p.approved_by);
    if (!user) return res.json({ status: 'expired' });
    res.json({ status: 'approved', token: deviceTokenFor(user, p.device_id),
               user: publicUser(user), device_id: p.device_id });
  } catch (err) {
    console.error('device/poll failed:', err);
    res.status(500).json({ error: 'Poll failed.' });
  }
});

app.delete('/api/device/:id', async (req, res) => {
  const user = await requireUser(req, res);
  if (!user) return;
  const users = await readUsers();
  const u = users.find((x) => x.id === user.id);
  u.devices = (u.devices || []).filter((d) => d.id !== req.params.id);
  await writeUsers(users);
  res.json({ revoked: true });
});

// Admin authentication endpoint
app.post('/api/auth/admin', async (req, res) => {
  const { password } = req.body;

  if (!password) {
    return res.status(400).json({ error: 'Password required' });
  }

  try {
    // You can generate a new hash by running: node -e "const bcrypt = require('bcrypt'); bcrypt.hash('yourpassword', 10).then(console.log)"
    const passwordHash = process.env.ADMIN_PASSWORD_HASH;

    if (!passwordHash) {
      return res.status(500).json({ error: 'Admin password not configured' });
    }

    const isValid = await bcrypt.compare(password, passwordHash);

    if (isValid) {
      res.json({ success: true, isAdmin: true });
    } else {
      res.status(401).json({ error: 'Invalid password' });
    }
  } catch (err) {
    console.error('Error verifying admin password:', err);
    res.status(500).json({ error: 'Authentication failed' });
  }
});

// Only start a long-running server when executed directly (local dev).
// On Vercel the app is imported by api/index.js and invoked per-request.
if (require.main === module) {
  initPostsFile().then(() => {
    app.listen(PORT, () => {
      console.log(`Server running on port ${PORT}`);
    });
  });
}

module.exports = app;
