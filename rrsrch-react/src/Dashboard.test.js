import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Dashboard, { layoutAtlas } from './Dashboard';

const GRAPH = {
  nodes: [
    { id: 'claim:1', kind: 'claim', claim_id: 1, label: 'WOMAC improved at 12 months', state: 'supported', type: 'empirical', open_challenges: 0 },
    { id: 'claim:2', kind: 'claim', claim_id: 2, label: 'Pain did not differ', state: 'contested', type: 'empirical', open_challenges: 1 },
    { id: 'agent:bot', kind: 'agent', label: 'bot' },
    { id: 'source:MED:1', kind: 'source', label: 'BM-MSC trial', source_id: 'MED:1', year: 2019, is_primary: true },
    { id: 'source:MED:2', kind: 'source', label: 'ADSC trial', source_id: 'MED:2', year: 2020, is_primary: true },
    { id: 'trial:NCT01', kind: 'trial', label: 'NCT01' },
  ],
  edges: [
    { from: 'agent:bot', rel: 'authored', to: 'claim:1' },
    { from: 'agent:bot', rel: 'authored', to: 'claim:2' },
    { from: 'claim:1', rel: 'supports', to: 'source:MED:1', spans: 1 },
    { from: 'claim:2', rel: 'supports', to: 'source:MED:2', spans: 1 },
    { from: 'source:MED:1', rel: 'reports', to: 'trial:NCT01' },
    { from: 'claim:1', rel: 'contradicts', to: 'claim:2' },
  ],
  counts: { claim: 2, agent: 1, source: 2, trial: 1 },
  claims_total: 2,
  truncated: false,
};

test('the atlas layout places every column without overlaps and filters by state', () => {
  const all = layoutAtlas(GRAPH, { state: 'all', text: '' });
  expect(all.nodes).toHaveLength(6);
  const ys = ['source:MED:1', 'source:MED:2'].map((id) => all.pos[id].y);
  expect(Math.abs(ys[0] - ys[1])).toBeGreaterThanOrEqual(30);
  const supported = layoutAtlas(GRAPH, { state: 'supported', text: '' });
  expect(supported.nodes.map((n) => n.id).sort()).toEqual(['agent:bot', 'claim:1', 'source:MED:1', 'trial:NCT01']);
  expect(supported.edges.some((e) => e.rel === 'contradicts')).toBe(false);   // its other end is filtered out
  expect(layoutAtlas(GRAPH, { state: 'all', text: 'pain' }).nodes.filter((n) => n.kind === 'claim')).toHaveLength(1);
});

function mockEngine(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const path = url.replace(/^\/api\/engine/, '');
    const hit = Object.entries(routes).find(([p]) => path.startsWith(p));
    const [status, body] = hit ? hit[1](opts) : [404, { ok: false, error: 'not found' }];
    return { ok: status < 400, status, statusText: '', json: async () => body };
  });
  return calls;
}

beforeEach(() => localStorage.clear());

test('connecting with a key shows who you are and sends the key to the engine only', async () => {
  const calls = mockEngine({
    '/health': () => [200, { ok: true, claims: 12 }],
    '/v1/repos': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 12 }] }],
    '/v1/agents': () => [200, { ok: true, items: [{ handle: 'demetri', kind: 'human', status: 'active' }] }],
    '/v1/whoami': (o) => (o.headers?.Authorization === 'Bearer rrsrch_good'
      ? [200, { ok: true, handle: 'demetri', organization_id: 'rrsrch', org_role: 'admin', status: 'active', scopes: ['agents', 'read'] }]
      : [401, { ok: false, error: 'invalid, expired or revoked key' }]),
  });
  render(<Dashboard isMobile={false} accountPanel={<div>account</div>} />);
  expect(await screen.findByText(/engine live · 12 claims/)).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText('rrsrch_…'), { target: { value: 'rrsrch_bad' } });
  fireEvent.click(screen.getByText('Connect'));
  expect(await screen.findByText(/was not accepted/)).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText('rrsrch_…'), { target: { value: 'rrsrch_good' } });
  fireEvent.click(screen.getByText('Connect'));
  expect(await screen.findByText('Register an agent in rrsrch')).toBeInTheDocument();
  expect(localStorage.getItem('rrsrch_engine_key')).toBe('rrsrch_good');
  expect(calls.every((c) => c.url.startsWith('/api/engine'))).toBe(true);
});

test('the atlas tab draws the repository map and opens a claim', async () => {
  mockEngine({
    '/health': () => [200, { ok: true, claims: 2 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 2 }] }],
    '/v1/repos/rrsrch/msc-knee-oa/atlas': () => [200, { ok: true, repository: 'rrsrch/msc-knee-oa', ...GRAPH }],
    '/v1/claims/1': () => [200, { ok: true, claim: { id: 1, proposition: 'WOMAC improved at 12 months', state: 'supported',
      type: 'empirical', contributor: 'bot', head: { version: 1, content_hash: 'a'.repeat(64) }, evidence: [],
      verification: { passed: true }, challenges: [], contradicted_by: [], agrees_with: [] } }],
    '/v1/agents': () => [200, { ok: true, items: [] }],
  });
  render(<Dashboard isMobile={false} initialTab="atlas" accountPanel={null} />);
  const label = async () => (await screen.findAllByText('WOMAC improved at 12 months')).find((el) => el.tagName === 'text');
  expect(await label()).toBeTruthy();                                  // the node, beside its <title> tooltip
  expect(screen.getByText('2 claims')).toBeInTheDocument();
  fireEvent.click(await label());
  await waitFor(() => expect(screen.getByText('Claim 1')).toBeInTheDocument());
  expect(await screen.findByText('checks passed')).toBeInTheDocument();
});

test('a deep link from a search citation opens that claim in the atlas', async () => {
  window.location.hash = '#/agents?tab=atlas&repo=rrsrch%2Fmsc-knee-oa&claim=2';
  mockEngine({
    '/health': () => [200, { ok: true, claims: 2 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/other', claims: 0 }, { slug: 'rrsrch/msc-knee-oa', claims: 2 }] }],
    '/v1/repos/rrsrch/msc-knee-oa/atlas': () => [200, { ok: true, repository: 'rrsrch/msc-knee-oa', ...GRAPH }],
    '/v1/claims/2': () => [200, { ok: true, claim: { id: 2, proposition: 'Pain did not differ', state: 'contested',
      type: 'empirical', contributor: 'bot', head: null, evidence: [], verification: null,
      challenges: [{ id: 9, kind: 'scope', state: 'open', author: 'ext' }], contradicted_by: [], agrees_with: [] } }],
  });
  render(<Dashboard isMobile={false} accountPanel={null} />);
  expect(await screen.findByText('Claim 2')).toBeInTheDocument();
  expect(await screen.findByText(/Challenge 9 \(scope, open\) by ext/)).toBeInTheDocument();
  window.location.hash = '';
});

test('claims are reviewed against their passage, and the result says where the claim stands', async () => {
  const item = { id: 41, proposition: 'WOMAC improved more with MSCs at 12 months.', state: 'structurally_valid',
    type: 'empirical', contributor: 'rrsrch-reader', source_id: 'MED:1', source_title: 'BM-MSC trial', year: 2019,
    open_challenges: 0, reviews: [],
    passage: { before: 'Results: ', excerpt: 'At 12 months, WOMAC scores improved more with MSCs', after: ', while VAS pain…' } };
  const calls = mockEngine({
    '/health': () => [200, { ok: true, claims: 1 }],
    '/v1/whoami': () => [200, { ok: true, handle: 'demetri', organization_id: 'rrsrch', org_role: 'admin', status: 'active', scopes: ['review', 'read'] }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 1 }] }],
    '/v1/repos/rrsrch/msc-knee-oa/review-queue': () => [200, { ok: true, items: [item], next: null, waiting: 1 }],
    '/v1/claims/41/reviews': (o) => [200, { ok: true, claim_id: 41, state: 'supported', approvals: 1, reasons: [] }],
  });
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  render(<Dashboard isMobile={false} initialTab="review" accountPanel={null} />);
  expect(await screen.findByText('WOMAC improved more with MSCs at 12 months.')).toBeInTheDocument();
  expect(screen.getByText('At 12 months, WOMAC scores improved more with MSCs').tagName).toBe('MARK');
  expect(screen.getByText('1 waiting')).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText(/What you checked/), { target: { value: 'matches' } });
  fireEvent.click(screen.getByText('Approve'));
  expect(await screen.findByText('supported')).toBeInTheDocument();
  const sent = calls.find((c) => c.url.endsWith('/v1/claims/41/reviews'));
  expect(JSON.parse(sent.opts.body)).toEqual({ verdict: 'approve', findings: 'matches' });
  expect(sent.opts.headers.Authorization).toBe('Bearer rrsrch_k');
});
