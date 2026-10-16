import { render, screen, fireEvent, within } from '@testing-library/react';
import AgentsHome, { statusOf, trackOf } from './AgentsRoster';

const hoursAgo = (h) => new Date(Date.now() - h * 3600e3).toISOString();

test('status: working with open posts or recent action, waiting with only open proposals, else idle', () => {
  expect(statusOf({ posts: [{ id: 1, status: 'open', title: 'Q', created_at: hoursAgo(5) }], proposals: [],
    last_active_at: hoursAgo(5) }).status).toBe('working');
  expect(statusOf({ posts: [], proposals: [], last_active_at: hoursAgo(0.2) }).status).toBe('working');
  expect(statusOf({ posts: [], proposals: [{ id: 2, state: 'open', proposition: 'P', created_at: hoursAgo(3) }],
    last_active_at: hoursAgo(3) }).status).toBe('waiting');
  expect(statusOf({ posts: [{ id: 3, status: 'closed' }], proposals: [{ id: 4, state: 'merged' }],
    last_active_at: hoursAgo(48) }).status).toBe('idle');
});

test('track record: the measure with the most evaluations; a rate only from 5', () => {
  const t = trackOf({ impetus: { outcomes: [
    { metric: 'accuracy', count: 27, of: 31, rate: 0.871, lower_bound: 0.71, meaning: 'claims supported' },
    { metric: 'review_judgement', count: 2, of: 3, rate: null, lower_bound: null } ] } });
  expect([t.metric, t.rated, t.color]).toEqual(['accuracy', true, '#00ff88']);
  const few = trackOf({ impetus: { outcomes: [{ metric: 'accuracy', count: 3, of: 4, rate: null, lower_bound: null }] } });
  expect(few.rated).toBe(false);
  expect(trackOf({ impetus: { outcomes: [{ metric: 'accuracy', count: 0, of: 0 }] } })).toBeNull();
});

const DATA = {
  '/v1/agents?organization=lab': { items: [
    { handle: 'trial-reader', kind: 'service', model: 'qwen', status: 'active', organization_id: 'lab' },
    { handle: 'old-bot', kind: 'service', status: 'active', organization_id: 'lab' }] },
  '/v1/agents/trial-reader/work': { last_active_at: hoursAgo(2), posts: [], proposals: [
    { id: 7, state: 'open', proposition: '42% responded at 24 months.', repository: 'lab/knee', created_at: hoursAgo(2) }] },
  '/v1/agents/old-bot/work': { last_active_at: hoursAgo(200), posts: [], proposals: [] },
  '/v1/agents/trial-reader/standing': { impetus: { outcomes: [{ metric: 'accuracy', count: 9, of: 10, rate: 0.9,
    lower_bound: 0.6, meaning: 'claims supported' }] }, trust: { domains: [{ domain: 'lab/knee', evaluations: 10,
    rate: 0.9, lower_bound: 0.6 }] } },
  '/v1/agents/old-bot/standing': { impetus: { outcomes: [] }, trust: { domains: [] } },
  '/v1/agents/trial-reader/activity': { days: Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(3 + i).padStart(2, '0')}`,
    count: i === 13 ? 2 : 0, outcome: i === 13 ? 'waiting' : null })) },
  '/v1/agents/old-bot/activity': { days: [] },
  '/v1/organizations/lab/activity': { items: [{ kind: 'proposal', id: 7, handle: 'trial-reader', at: hoursAgo(2),
    verb: 'proposed', title: '42% responded at 24 months.' }] },
  '/v1/agents?organization=unclaimed': { items: [] },
};

test('the Agents page: right now, the roster with status filters, and the selected agent', async () => {
  global.fetch = jest.fn((url) => {
    const path = url.replace('/api/engine', '').replace(/&limit=\d+$/, '');
    const key = Object.keys(DATA).find((k) => path === k || path.startsWith(`${k}?`));
    return Promise.resolve({ ok: !!key, status: key ? 200 : 404, json: () => Promise.resolve({ ok: !!key, ...(DATA[key] || {}) }) });
  });
  const me = { handle: 'admin', organization_id: 'lab', org_role: 'admin', scopes: ['agents', 'read'] };
  render(<AgentsHome apiKey="k" me={me} isMobile={false} repos={[]} repo="lab/knee" onRepo={() => {}} />);
  const now = await screen.findByRole('region', { name: 'Right now' });
  await within(now).findByText('proposed');
  expect(now).toHaveTextContent('trial-reader proposed 42% responded');
  const roster = await screen.findByRole('table', { name: 'Your agents' });
  expect(await within(roster).findByText('old-bot')).toBeInTheDocument();
  expect(within(roster).getByText('90%')).toBeInTheDocument();
  const detail = screen.getByRole('complementary', { name: 'trial-reader detail' });          // first agent selected
  expect(detail).toHaveTextContent('Working on now · 1');
  expect(detail).toHaveTextContent('waiting on reviewers');
  expect(detail).toHaveTextContent('trust 90% of 10');
  expect(screen.queryByText(/Sparks/i)).not.toBeInTheDocument();                             // dormant: never shown
  fireEvent.click(screen.getByRole('button', { name: /^idle/ }));
  expect(within(screen.getByRole('table', { name: 'Your agents' })).queryByText('trial-reader')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('row', { name: /old-bot/ }));
  expect(screen.getByRole('complementary', { name: 'old-bot detail' })).toHaveTextContent('No independent evaluations yet');
  fireEvent.click(screen.getByRole('button', { name: 'Timeline' }));
  expect(screen.getByRole('table', { name: 'Your agents over 14 days' })).toBeInTheDocument();
  expect(localStorage.getItem('rrsrch_agents_view')).toBe('timeline');
  localStorage.clear();
});
