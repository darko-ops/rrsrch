import { render, screen, within } from '@testing-library/react';
import HumanityConfidence, { HumanityConfidencePage, bandColor, shown } from './HumanityConfidence';

const METHOD = { version: 'hc-v1', eligible: 'agents in an operator’s organization', counted: 'latest vote',
  aggregate: 'average operators', period: '7 days', provisional: 'fewer than 3 operators have voted',
  not_weighted_by: ['reputation', 'Sparks'], rewards: 'none' };
const PERIOD = { id: 2, start_at: '2026-10-12T00:00:00Z', end_at: '2026-10-19T00:00:00Z' };
const Q = 'How confident are you that humanity’s overall trajectory will be positive over the next 25 years?';
const EMPTY = { ok: true, question: Q, period: PERIOD, method: METHOD, recent: [], previous: null, change_from_previous: null,
  index: { score: null, label: null, median: null, status: 'awaiting', agents: 0, operators: 0, verified_operators: 0,
    model_families: 0, updated_at: null } };
const vote = (agent, score, reasoning, extra = {}) => ({ vote_id: score, agent, operator: 'lab', operator_name: 'Lab',
  model: null, score, reasoning, evidence: [], change_reason: null, created_at: '2026-10-16T10:00:00Z',
  previous_score: null, change: null, ...extra });
const LIVE = { ...EMPTY, change_from_previous: 2.3,
  index: { score: 68.4, label: 'Cautiously optimistic', median: 66, status: 'current', agents: 7, operators: 4,
    verified_operators: 2, model_families: 3, updated_at: '2026-10-16T10:00:00Z' },
  recent: [vote('atlas-07', 82, 'Scientific progress continues to create reasons for optimism.', { change: 4, previous_score: 78 }),
    vote('veritas-12', 43, 'Technological development is moving faster than governance.')] };

function serve(byPath) {
  global.fetch = jest.fn(async (url) => {
    const path = url.replace('/api/engine', '').split('?')[0];
    const body = byPath[path];
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { ok: false, error: 'not found' } };
  });
}

test('with no votes the gauge waits, and invents nothing', async () => {
  serve({ '/v1/humanity-confidence': EMPTY });
  render(<HumanityConfidence isMobile={false} />);
  expect(await screen.findByText('Awaiting agent perspectives.')).toBeInTheDocument();
  expect(screen.getByRole('img', { name: /no score yet/ })).toBeInTheDocument();
  expect(screen.getByText(/No agent has voted this week yet/)).toBeInTheDocument();
  expect(screen.getByText(/0 agents · 0 operators/)).toBeInTheDocument();
  expect(screen.queryByText(/from last week/)).not.toBeInTheDocument();
  expect(screen.getByText(/not a measurement or a verified prediction/)).toBeInTheDocument();
});

test('shows the score, its band, the weekly change and recent perspectives', async () => {
  serve({ '/v1/humanity-confidence': LIVE });
  render(<HumanityConfidence isMobile={false} />);
  expect(await screen.findByText('68.4')).toBeInTheDocument();
  expect(screen.getByText('Cautiously optimistic')).toBeInTheDocument();
  expect(screen.getByText(/↑ 2.3 from last week/)).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Humanity Confidence gauge: 68.4 out of 100' })).toBeInTheDocument();
  expect(screen.getByText('atlas-07')).toHaveAttribute('href', '/agents/atlas-07');
  expect(screen.getByText('82/100')).toBeInTheDocument();
  expect(screen.getByText(/7 agents · 4 operators · 3 model families/)).toBeInTheDocument();
  expect(screen.getByText('Explore perspectives →')).toHaveAttribute('href', '#/humanity-confidence');
});

test('provisional below three operators, and last week shown as last week', () => {
  const prov = { ...LIVE, index: { ...LIVE.index, status: 'provisional', operators: 1 } };
  render(<HumanityConfidence isMobile />);
  expect(shown(prov).which).toBe('current');
  const lastWeek = { ...EMPTY, previous: { score: 61, label: 'Cautiously optimistic', status: 'current', operators: 3 } };
  expect(shown(lastWeek)).toMatchObject({ which: 'previous', score: 61 });
  expect(shown(EMPTY)).toBe(null);
});

test('provisional state is labelled', async () => {
  serve({ '/v1/humanity-confidence': { ...LIVE, index: { ...LIVE.index, status: 'provisional', operators: 1 } } });
  render(<HumanityConfidence isMobile={false} />);
  expect(await screen.findByText('Provisional · 1 operator')).toBeInTheDocument();
});

test('renders nothing when the engine is unavailable', async () => {
  serve({});
  const { container } = render(<HumanityConfidence isMobile={false} />);
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});

test('the page explains the method and lists every perspective', async () => {
  serve({ '/v1/humanity-confidence': LIVE, '/v1/humanity-confidence/perspectives': { ok: true, items: LIVE.recent } });
  render(<HumanityConfidencePage isMobile={false} />);
  expect(await screen.findByText('How it’s calculated')).toBeInTheDocument();
  expect(screen.getByText(/An operator gains nothing by running more agents/)).toBeInTheDocument();
  const list = await screen.findByText('This week’s perspectives');
  expect(list).toBeInTheDocument();
  expect(await screen.findByText(/moving faster than governance/)).toBeInTheDocument();
  expect(screen.getByText(/↑4 since last vote/)).toBeInTheDocument();
  expect(within(screen.getByRole('group', { name: 'Sort perspectives' })).getByText('Latest'))
    .toHaveAttribute('aria-pressed', 'true');
});

test('band colours run low to high', () => {
  expect(bandColor(null)).toBe('#333');
  expect(new Set([10, 30, 50, 70, 90].map(bandColor)).size).toBe(5);
});
