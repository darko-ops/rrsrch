import { render, screen, fireEvent, within } from '@testing-library/react';
import Directory from './Directory';

const ITEMS = [
  { handle: 'scout', operator: 'harbor-lab', claimed: true, kind: 'model', model: 'acme/m1', description: 'Reads trials',
    posts: 3, replies: 1, reviews: 0, gauges: 2, followers: 1, sparks_7d: 7, last_active: new Date().toISOString(),
    joined_at: '2026-10-01T00:00:00Z' },
  { handle: 'newbie', operator: 'unclaimed', claimed: false, kind: 'model', model: null, description: '',
    posts: 0, replies: 0, reviews: 0, gauges: 0, followers: 0, sparks_7d: 0, last_active: null,
    joined_at: '2026-10-19T00:00:00Z' },
];

function serve(calls = []) {
  let subs = [];
  global.fetch = jest.fn((url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    calls.push([opts.method || 'GET', path]);
    const ok = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, ...d }) });
    if (path.startsWith('/v1/agents/directory')) return ok({ sort: 'active', total: ITEMS.length, items: ITEMS });
    if (path === '/v1/subscriptions' && opts.method === 'POST') {
      subs = [...subs, JSON.parse(opts.body).target];
      return ok({ subscriptions: subs });
    }
    if (path === '/v1/subscriptions') return ok({ subscriptions: subs });
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ ok: false, error: 'not found' }) });
  });
  return calls;
}

afterEach(() => localStorage.clear());

test('lists the network\'s agents with what they have done', async () => {
  serve();
  render(<Directory me={null} />);
  const card = (await screen.findByRole('link', { name: 'scout' })).closest('article');
  expect(card).toHaveTextContent('harbor-lab');
  expect(card).toHaveTextContent('7 Sparks this week');
  expect(card).toHaveTextContent('3 posts');
  expect(screen.getByText('unclaimed')).toBeInTheDocument();
  expect(screen.getByText('Sign in to follow agents.')).toBeInTheDocument();
});

test('signed in, you can follow an agent, and the sort and search go to the engine', async () => {
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  const calls = serve();
  render(<Directory me={{ handle: 'dana' }} />);
  const card = (await screen.findByRole('link', { name: 'scout' })).closest('article');
  fireEvent.click(await within(card).findByRole('button', { name: 'Follow' }));
  expect(await within(card).findByRole('button', { name: 'Following' })).toBeInTheDocument();
  expect(card).toHaveTextContent('2 followers');
  fireEvent.click(screen.getByRole('button', { name: 'Sparks this week' }));
  await screen.findAllByRole('article');
  expect(calls.some(([, p]) => p.startsWith('/v1/agents/directory?sort=sparks'))).toBe(true);
});
