// Response headers, removed routes, links from engine data, and the production secret check.  Run: npm run test:server
const test = require('node:test');
const assert = require('node:assert');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const app = require('../server');
const { joinPage } = require('../server');

async function withServer(fn) {
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  try {
    return await fn(`http://127.0.0.1:${server.address().port}`);
  } finally {
    server.close();
  }
}

test('every response carries the security headers', () => withServer(async (base) => {
  // (Express's own 404 page sets a stricter CSP of its own, default-src 'none')
  for (const url of ['/signal.json', '/api/account/config', '/join']) {
    const r = await fetch(base + url);
    const csp = r.headers.get('content-security-policy') || '';
    assert.match(csp, /default-src 'self'/, url);
    assert.match(csp, /frame-ancestors 'none'/, url);
    assert.match(csp, /script-src 'self' https:\/\/accounts\.google\.com\/gsi\/client(;|$)/, url);
    assert.strictEqual(r.headers.get('x-frame-options'), 'DENY', url);
    assert.strictEqual(r.headers.get('x-content-type-options'), 'nosniff', url);
    assert.strictEqual(r.headers.get('referrer-policy'), 'strict-origin-when-cross-origin', url);
    assert.ok(r.headers.get('permissions-policy'), url);
  }
}));

test('the removed routes are gone', () => withServer(async (base) => {
  for (const [method, url] of [['GET', '/api/web/search?q=x'], ['GET', '/api/literature/search?q=x'],
    ['GET', '/api/stock/AAPL'], ['GET', '/api/stocks'], ['GET', '/api/markets'], ['GET', '/api/etfs'],
    ['GET', '/api/tweets'], ['POST', '/api/web/arguments'], ['POST', '/api/search/followups'],
    ['GET', '/api/posts'], ['POST', '/api/posts'], ['DELETE', '/api/posts/1'], ['POST', '/api/auth/admin'],
    ['GET', '/api/auth/user'], ['GET', '/api/auth/logout']]) {
    const r = await fetch(base + url, { method });
    assert.strictEqual(r.status, 404, `${method} ${url}`);
  }
}));

test('account deletion needs a signed-in account first', () => withServer(async (base) => {
  const r = await fetch(`${base}/api/account/me`, { method: 'DELETE' });
  assert.strictEqual(r.status, 401);
}));

test('/join links an open question only to an http(s) address', () => {
  const html = joinPage({ needs: { open_questions: 2 }, questions: [
    { id: 4, title: 'bad', url: 'javascript:alert(1)' },
    { id: 5, title: 'good', url: 'https://rrsrch.com/questions/5' },
  ] }, null);
  assert.doesNotMatch(html, /javascript:/);
  assert.match(html, /href="https:\/\/rrsrch\.com\/#\/posts\/4">bad</);
  assert.match(html, /href="https:\/\/rrsrch\.com\/questions\/5">good</);
});

test('production refuses to start without SESSION_SECRET', () => {
  const run = (env) => spawnSync(process.execPath, ['-e', `require(${JSON.stringify(path.join(__dirname, '..', 'server.js'))})`],
    { cwd: os.tmpdir(), env: { PATH: process.env.PATH, SESSION_SECRET: '', ...env }, encoding: 'utf8' });
  for (const env of [{ NODE_ENV: 'production' }, { VERCEL: '1', VERCEL_ENV: 'production', NODE_ENV: 'production' }]) {
    const out = run(env);
    assert.notStrictEqual(out.status, 0, JSON.stringify(env));
    assert.match(out.stderr, /SESSION_SECRET is not set/);
  }
  assert.strictEqual(run({ SESSION_SECRET: 'a-test-secret', NODE_ENV: 'production' }).status, 0);
  assert.strictEqual(run({}).status, 0);
  // a Vercel preview runs with NODE_ENV=production and no SESSION_SECRET: it starts on the development value
  assert.strictEqual(run({ VERCEL: '1', VERCEL_ENV: 'preview', NODE_ENV: 'production' }).status, 0);
});
