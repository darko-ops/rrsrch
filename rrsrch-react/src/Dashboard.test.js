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

test('connecting a key on the Account page signs in as that agent, sending the key to the engine only', async () => {
  const calls = mockEngine({
    '/health': () => [200, { ok: true, claims: 12 }],
    '/v1/repos': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 12 }] }],
    '/v1/me/counts': () => [200, { ok: true, queue: 3, merge: 1, tasks: 0, agents: 2, keys: 1, inbox_unread: 4 }],
    '/v1/agents': () => [200, { ok: true, items: [{ handle: 'demetri', kind: 'human', status: 'active' }] }],
    '/v1/whoami': (o) => (o.headers?.Authorization === 'Bearer rrsrch_good'
      ? [200, { ok: true, handle: 'demetri', organization_id: 'rrsrch', org_role: 'admin', status: 'active', scopes: ['agents', 'read'] }]
      : [401, { ok: false, error: 'invalid, expired or revoked key' }]),
  });
  render(<Dashboard isMobile={false} initialTab="account" />);
  expect(await screen.findByText('Connect an agent key')).toBeInTheDocument();      // signed out: no sidebar
  expect(screen.queryByRole('button', { name: /^Review/ })).not.toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText('rrsrch_…'), { target: { value: 'rrsrch_bad' } });
  fireEvent.click(screen.getByText('Connect'));
  expect(await screen.findByText(/was not accepted/)).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText('rrsrch_…'), { target: { value: 'rrsrch_good' } });
  fireEvent.click(screen.getByText('Connect'));
  expect(await screen.findByText('Acting as demetri')).toBeInTheDocument();         // Account, as demetri (no Agents sidebar)
  expect(localStorage.getItem('rrsrch_engine_key')).toBe('rrsrch_good');
  const keyed = calls.filter((c) => String(c.opts.headers?.Authorization || '').includes('rrsrch_'));
  expect(keyed.length).toBeGreaterThan(0);
  expect(keyed.every((c) => c.url.startsWith('/api/engine'))).toBe(true);           // the key only goes to the engine
  localStorage.clear();
});

test('the tab row lists the pages with their counts and switches between them', async () => {
  mockEngine({
    '/health': () => [200, { ok: true, claims: 12 }],
    '/v1/repos': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 12 }] }],
    '/v1/me/counts': () => [200, { ok: true, queue: 313, merge: 2, tasks: 1 }],
    '/v1/agents': () => [200, { ok: true, items: [] }],
    '/v1/repos/rrsrch/msc-knee-oa/merge-requests': () => [200, { ok: true, items: [], next: null }],
  });
  render(<Dashboard isMobile={false} initialTab="agents" />);
  expect(await screen.findByText(/engine live · 12 claims/)).toBeInTheDocument();
  expect(await screen.findByText('315')).toBeInTheDocument();                 // one count: 313 claims + 2 proposals
  expect(screen.getByRole('navigation', { name: 'Agents pages' })).toBeInTheDocument();   // tabs, not a sidebar
  expect(screen.queryByRole('button', { name: /Merge requests/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Review|^Inbox/ })).not.toBeInTheDocument();   // both are Tasks now
  fireEvent.click(screen.getByRole('button', { name: /^Tasks/ }));
  expect((await screen.findAllByRole('heading', { name: 'Proposed changes' })).length).toBeGreaterThan(0);
  expect(window.location.hash).toBe('#/agents?tab=tasks');
  window.location.hash = '';
});

test('Tasks: what\'s addressed to you first, then what\'s waiting for review; old Review and Inbox links open it', async () => {
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  window.location.hash = '#/agents?tab=inbox';
  mockEngine({
    '/health': () => [200, { ok: true, claims: 12 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 12 }] }],
    '/v1/me/counts': () => [200, { ok: true, queue: 3, merge: 0 }],
    '/v1/whoami': () => [200, { ok: true, handle: 'bot', organization_id: 'lab', org_role: 'member', scopes: ['read'] }],
    '/v1/inbox': () => [200, { ok: true, unread: 1, items: [{ id: 'n1', type: 'mention', read: false, at: '2026-10-18T00:00:00Z',
      title: 'bot was mentioned on post 4', target: 'post:4', detail: {} }] }],
    '/v1/repos/rrsrch/msc-knee-oa/merge-requests': () => [200, { ok: true, items: [], next: null }],
  });
  render(<Dashboard isMobile={false} />);
  expect(await screen.findByRole('heading', { name: 'Tasks' })).toBeInTheDocument();
  expect(await screen.findByText('For you')).toBeInTheDocument();
  expect(await screen.findByText('bot was mentioned on post 4')).toBeInTheDocument();
  expect(await screen.findByText('1 new')).toBeInTheDocument();                         // unread, beside the tab
  expect((await screen.findAllByRole('heading', { name: 'Proposed changes' })).length).toBeGreaterThan(0);
  window.location.hash = '';
  localStorage.clear();
});

test('the atlas page draws the repository map with its drawer', async () => {
  mockEngine({
    '/health': () => [200, { ok: true, claims: 2 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 2 }] }],
    '/v1/me/counts': () => [200, { ok: true }],
    '/v1/repos/rrsrch/msc-knee-oa/atlas': () => [200, { ok: true, repository: 'rrsrch/msc-knee-oa', ...GRAPH }],
  });
  render(<Dashboard isMobile={false} initialTab="atlas" />);
  expect(await screen.findByText('Showing 2 of 2 claims')).toBeInTheDocument();
  expect(screen.getByText('esc to close')).toBeInTheDocument();
});

test('a deep link from a search citation opens that claim in the atlas', async () => {
  window.location.hash = '#/agents?tab=atlas&repo=rrsrch%2Fmsc-knee-oa&claim=2';
  mockEngine({
    '/health': () => [200, { ok: true, claims: 2 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/other', claims: 0 }, { slug: 'rrsrch/msc-knee-oa', claims: 2 }] }],
    '/v1/me/counts': () => [200, { ok: true }],
    '/v1/repos/rrsrch/msc-knee-oa/atlas': () => [200, { ok: true, repository: 'rrsrch/msc-knee-oa', ...GRAPH }],
  });
  render(<Dashboard isMobile={false} />);
  expect(await screen.findByText('rrsrch/msc-knee-oa ▾')).toBeInTheDocument();
  expect(await screen.findByText(/Open the claim page/)).toHaveAttribute('href', '/claims/2');
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
    '/v1/reviews': (o) => [200, { ok: true, claim_id: 41, state: 'supported', approvals: 1, reasons: [] }],
  });
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  localStorage.setItem('rrsrch_review_mode', 'single');
  render(<Dashboard isMobile={false} initialTab="review" />);
  expect(await screen.findByText('WOMAC improved more with MSCs at 12 months.')).toBeInTheDocument();
  expect(screen.getByText('At 12 months, WOMAC scores improved more with MSCs').tagName).toBe('MARK');
  expect(screen.getByText('1 waiting')).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText(/What you checked/), { target: { value: 'matches' } });
  fireEvent.click(screen.getByText('Approve'));
  expect(await screen.findByText('supported')).toBeInTheDocument();
  const sent = calls.find((c) => c.url.endsWith('/v1/reviews'));
  expect(JSON.parse(sent.opts.body)).toEqual({ target: 'claim:41', verdict: 'approve', findings: 'matches' });
  expect(sent.opts.headers.Authorization).toBe('Bearer rrsrch_k');
});

test('old links to the review queue, merge requests or tasks open the one Review page', async () => {
  window.location.hash = '#/agents?tab=tasks';
  mockEngine({
    '/health': () => [200, { ok: true, claims: 1 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 1 }] }],
    '/v1/me/counts': () => [200, { ok: true }],
    '/v1/repos/rrsrch/msc-knee-oa/merge-requests': () => [200, { ok: true, items: [], next: null }],
    '/v1/repos/rrsrch/msc-knee-oa/review-queue': () => [200, { ok: true, items: [], next: null, waiting: 0 }],
  });
  render(<Dashboard isMobile={false} />);
  expect((await screen.findAllByRole('heading', { name: 'Proposed changes' })).length).toBeGreaterThan(0);
  expect(await screen.findByText('No proposals waiting.')).toBeInTheDocument();
  expect(screen.getByText('Claims already in the repository, not yet reviewed')).toBeInTheDocument();
  window.location.hash = '';
});

test('the Bounties page is in the sidebar only where the engine has bounties on', async () => {
  const routes = (mode) => ({
    '/health': () => [200, { ok: true, claims: 1 }],
    '/v1/repos?': () => [200, { ok: true, items: [{ slug: 'rrsrch/msc-knee-oa', claims: 1 }] }],
    '/v1/me/counts': () => [200, { ok: true }],
    '/v1/agents': () => [200, { ok: true, items: [] }],
    '/v1/bounties': () => [200, { ok: true, mode, items: [], next: null }],
  });
  mockEngine(routes('off'));
  const { unmount } = render(<Dashboard isMobile={false} initialTab="agents" />);
  expect(await screen.findByRole('button', { name: /^Tasks/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Bounties/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Inbox/ })).not.toBeInTheDocument();      // part of Tasks now
  expect(screen.queryByRole('button', { name: /^Atlas/ })).not.toBeInTheDocument();
  unmount();
  mockEngine(routes('on'));                     // operator mode shows it to RRSRCH operators only
  render(<Dashboard isMobile={false} initialTab="agents" />);
  expect(await screen.findByRole('button', { name: /^Bounties/ })).toBeInTheDocument();
});
