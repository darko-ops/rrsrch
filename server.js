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

// Open-web search (Comet-like layer). Prefer Brave, then Serper. Not the evidence ledger.
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
  const results = (data.web?.results || []).map((r) => ({
    title: r.title || 'Untitled',
    url: r.url || null,
    snippet: r.description || '',
    source: (() => { try { return new URL(r.url).hostname.replace(/^www\./, ''); } catch { return null; } })(),
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
  const results = (data.organic || []).map((r) => ({
    title: r.title || 'Untitled',
    url: r.link || null,
    snippet: r.snippet || '',
    source: (() => { try { return new URL(r.link).hostname.replace(/^www\./, ''); } catch { return null; } })(),
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
    results.push({
      title,
      url: href,
      snippet: snippets[i] || '',
      source,
    });
    i += 1;
  }
  return { provider: 'duckduckgo', results };
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
      results: packed.results,
      note: 'Open web — not gated ledger evidence. Research tool only, not medical advice.',
    });
  } catch (err) {
    console.error('web search failed', err);
    return res.status(500).json({ error: 'search failed' });
  }
});

// Literature search for the landing page (Europe PMC — same source as the evidence engine).
app.get('/api/literature/search', async (req, res) => {
  const q = String(req.query.q || '').trim();
  if (!q) {
    return res.status(400).json({ error: 'query required' });
  }
  if (q.length > 500) {
    return res.status(400).json({ error: 'query too long (500 characters max)' });
  }
  const pageSize = Math.min(Math.max(parseInt(req.query.limit, 10) || 12, 1), 25);
  try {
    const params = new URLSearchParams({
      query: q,
      format: 'json',
      pageSize: String(pageSize),
      resultType: 'core',
    });
    const upstream = await fetch(`${EUROPE_PMC_SEARCH}?${params}`);
    if (!upstream.ok) {
      return res.status(502).json({ error: 'Europe PMC is unavailable' });
    }
    const data = await upstream.json();
    const raw = data.resultList?.result || [];
    const hitCount = parseInt(data.hitCount, 10) || raw.length;
    const results = raw.map((r) => {
      const pmcid = r.pmcid ? String(r.pmcid).replace(/^PMC/i, '') : null;
      let url = null;
      if (r.pmid) url = `https://europepmc.org/article/MED/${r.pmid}`;
      else if (pmcid) url = `https://europepmc.org/article/PMC/${pmcid}`;
      else if (r.doi) url = `https://doi.org/${r.doi}`;
      const abstract = String(r.abstractText || '').trim();
      return {
        pmid: r.pmid || null,
        pmcid: pmcid ? `PMC${pmcid}` : null,
        doi: r.doi || null,
        title: r.title || 'Untitled',
        authors: r.authorString || null,
        journal: r.journalTitle || null,
        year: r.pubYear || null,
        abstract: abstract.length > 2400 ? `${abstract.slice(0, 2400)}…` : abstract,
        openAccess: r.isOpenAccess === 'Y',
        url,
      };
    });
    res.json({ query: q, hitCount, results, source: 'Europe PMC' });
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
