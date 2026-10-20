import { render, screen, fireEvent, within } from '@testing-library/react';
import AgentsHome, { statusOf, trackOf, roleOf, missionOf, composeProtocol, parseProtocol } from './AgentsRoster';
import { markCells } from './AgentCard';

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
  '/v1/sparks/leaderboard?days=7': { days: 7, items: [{ rank: 1, agent: 'trial-reader', operator: 'lab', sparks: 12,
    from_activity: 8, from_quality: 4, penalties: 0, quality_share: 0.33, contributions: 9 }] },
  '/v1/agents?organization=lab': { items: [
    { handle: 'trial-reader', kind: 'service', model: 'qwen', status: 'active', organization_id: 'lab' },
    { handle: 'old-bot', kind: 'service', status: 'active', organization_id: 'lab' },
    { handle: 'dana', kind: 'human', status: 'active', organization_id: 'lab' }] },
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
  '/v1/organizations/lab/activity': { items: [{ kind: 'post', id: 9, handle: 'dana', at: hoursAgo(1), verb: 'asked',
    title: 'A person asking' }, { kind: 'proposal', id: 7, handle: 'trial-reader', at: hoursAgo(2),
    verb: 'proposed', title: '42% responded at 24 months.' }] },
  '/v1/agents?organization=unclaimed': { items: [] },
  '/v1/agents/trial-reader': { agent: { handle: 'trial-reader', organization_id: 'lab', protocol: {
    text: 'Role: Trial reader\n\nMission: read knee OA trials.', updated_at: hoursAgo(3), updated_by: 'admin' } } },
};

test('the identity mark: the same 5x5 mirrored mark for a handle, every time', () => {
  const m = markCells('trial-reader');
  expect(m).toHaveLength(25);
  expect(markCells('trial-reader')).toEqual(m);
  for (let y = 0; y < 5; y++) {
    expect(m[y * 5 + 3]).toBe(m[y * 5 + 1]);
    expect(m[y * 5 + 4]).toBe(m[y * 5]);
  }
  expect(markCells('old-bot')).not.toEqual(m);
});

test('role and mission come from the protocol\'s "Role:" and "Mission:" lines', () => {
  const p = { text: 'Role: Trial reader\nMission: Read every knee OA trial\nand propose its outcomes.\n\nFocus:\n- MSCs' };
  expect(roleOf(p)).toBe('Trial reader');
  expect(missionOf(p)).toBe('Read every knee OA trial and propose its outcomes.');
  expect(missionOf({ text: 'Mission: one line\nFocus:\n- x' })).toBe('one line');
  expect(roleOf(null)).toBe('');
  expect(missionOf({ text: 'no labels here' })).toBe('');
});

test('the Agents page: right now, needs you, status filters and a card per agent linking to its profile', async () => {
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
  const cards = await screen.findByRole('region', { name: 'Your agents' });
  const reader = await within(cards).findByRole('link', { name: 'trial-reader, waiting on reviewers' });
  expect(reader).toHaveAttribute('href', '/agents/trial-reader');
  expect(reader).toHaveTextContent('waiting');
  expect(reader).toHaveTextContent('No. 001 · qwen');
  expect(reader).toHaveTextContent('Trial reader');                                       // its protocol's Role: line
  const old = within(cards).getByRole('link', { name: 'old-bot, idle' });
  expect(old).toHaveTextContent('No. 002');
  expect(old).toHaveTextContent('agent');                                                 // no role yet: its kind
  expect(old).toHaveTextContent('No orders yet');                                         // an admin sees which lack orders
  expect(reader).not.toHaveTextContent('No orders yet');
  const needs = screen.getByRole('region', { name: 'Needs you' });
  expect(needs).toHaveTextContent('Needs you · 1');
  expect(needs).toHaveTextContent('old-bot has no orders yet');
  expect(within(needs).getByRole('link', { name: 'Give it orders' })).toHaveAttribute('href', '/agents/old-bot?tab=protocol');
  expect(within(reader).getByTestId('identity-mark').children).toHaveLength(25);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();                           // the roster table is gone
  expect(within(cards).queryByRole('link', { name: /dana/ })).not.toBeInTheDocument();   // people get no card
  expect(within(cards).getAllByRole('link')).toHaveLength(2);
  expect(now).not.toHaveTextContent('A person asking');                                  // nor a line in Right now
  expect(screen.getByRole('button', { name: /^All/ })).toHaveTextContent('2');
  const board = screen.getByRole('region', { name: 'Leaderboard' });                     // public since 2026-10-20
  expect(await within(board).findByText('#1')).toBeInTheDocument();
  expect(within(board).getByText('trial-reader').closest('a')).toHaveAttribute('href', '/agents/trial-reader');
  expect(board).toHaveTextContent('12');
  expect(reader).toHaveTextContent('12 Sparks this week');
  expect(old).not.toHaveTextContent('Sparks this week');
  fireEvent.click(screen.getByRole('button', { name: /^idle/ }));
  expect(within(cards).queryByRole('link', { name: /trial-reader/ })).not.toBeInTheDocument();
  expect(within(cards).getByRole('link', { name: /old-bot/ })).toBeInTheDocument();
});

test('orders: the form writes the protocol text, and reads back only text in its own shape', () => {
  const f = { role: 'Trial reader', mission: 'Read knee OA trials\nand propose outcomes.', focus: '- MSC trials\n\n* PRP',
    sources: '', avoid: 'animal studies', unsure: '' };
  const text = composeProtocol(f);
  expect(text).toBe('Role: Trial reader\n\nMission: Read knee OA trials and propose outcomes.\n\nFocus:\n- MSC trials\n- PRP'
    + '\n\nAvoid:\n- animal studies');
  expect(parseProtocol(text)).toEqual({ role: 'Trial reader', mission: 'Read knee OA trials and propose outcomes.',
    focus: 'MSC trials\nPRP', sources: '', avoid: 'animal studies', unsure: '' });
  expect(parseProtocol('')).toEqual({ role: '', mission: '', focus: '', sources: '', avoid: '', unsure: '' });
  expect(parseProtocol('Mission: x\n\nBudget: 3 posts a day')).toBeNull();               // more than the form holds
  expect(parseProtocol('Just read trials.')).toBeNull();
});
