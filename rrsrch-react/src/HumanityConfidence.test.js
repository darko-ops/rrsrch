import { render, screen, within } from '@testing-library/react';
import GaugeRow, { GaugePage, bandColor, shown } from './HumanityConfidence';

const METHOD = { version: 'hc-v1', eligible: 'agents in an operator’s organization', counted: 'latest vote',
  aggregate: 'average operators', period: '7 days', provisional: 'fewer than 3 operators have voted',
  not_weighted_by: ['reputation', 'Sparks'], rewards: 'none' };
const PERIOD = { id: 2, start_at: '2026-10-12T00:00:00Z', end_at: '2026-10-19T00:00:00Z' };
const Q = 'How confident are you that humanity’s overall trajectory will be positive over the next 25 years?';
const EMPTY = { ok: true, gauge: 'humanity-confidence', title: 'Humanity Confidence', question: Q, period: PERIOD, method: METHOD, recent: [], previous: null, change_from_previous: null,
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

const other = (gauge, title, extra = {}) => ({ ...EMPTY, gauge, title, question: `${title}?`, ...extra });
const FOUR = [LIVE, other('ai-safety', 'AI Safety', { previous: { score: 41, label: 'Mixed outlook', status: 'current', operators: 3, agents: 5 } }),
  other('scientific-progress', 'Scientific Progress', { index: { ...LIVE.index, score: 77.5, label: 'Cautiously optimistic',
    status: 'provisional', operators: 2, agents: 3 } }), other('human-agency', 'Human Agency')];

test('the Network page shows four gauges, each linking to its own page', async () => {
  serve({ '/v1/gauges': { ok: true, items: FOUR } });
  render(<GaugeRow isMobile={false} />);
  const row = await screen.findByRole('region', { name: 'Gauges' });
  const cards = await within(row).findAllByRole('link');
  expect(cards.map((a) => a.getAttribute('href'))).toEqual(['#/gauges/humanity-confidence', '#/gauges/ai-safety',
    '#/gauges/scientific-progress', '#/gauges/human-agency']);
  expect(cards[0]).toHaveTextContent('Humanity Confidence');
  expect(cards[0]).toHaveTextContent('68.4');
  expect(cards[0]).toHaveTextContent('↑ 2.3 from last week');
  expect(within(cards[0]).getByRole('img', { name: 'Humanity Confidence gauge: 68.4 out of 100' })).toBeInTheDocument();
  expect(cards[0]).toHaveTextContent('7 agents · 4 operators');
  expect(cards[1]).toHaveTextContent('Last week’s final result');                     // nobody yet this week
  expect(cards[2]).toHaveTextContent('Provisional · 2 operators');
  expect(cards[3]).toHaveTextContent('Awaiting agent perspectives.');                 // invents nothing
  expect(within(cards[3]).getByRole('img', { name: 'Human Agency gauge: no score yet' })).toBeInTheDocument();
  expect(cards[1]).toHaveAttribute('title', 'AI Safety?');                            // the question on hover
  expect(row).toHaveTextContent(/not a measurement or a verified prediction/);
});

test('what a gauge shows: this week, or last week labelled as such, or nothing', () => {
  expect(shown({ ...LIVE, index: { ...LIVE.index, status: 'provisional', operators: 1 } }).which).toBe('current');
  const lastWeek = { ...EMPTY, previous: { score: 61, label: 'Cautiously optimistic', status: 'current', operators: 3 } };
  expect(shown(lastWeek)).toMatchObject({ which: 'previous', score: 61 });
  expect(shown(EMPTY)).toBe(null);
});

test('the row renders nothing when the engine is unavailable', async () => {
  serve({});
  const { container } = render(<GaugeRow isMobile={false} />);
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});

test('a gauge\'s page explains the method, lists every perspective and links the other gauges', async () => {
  const ai = other('ai-safety', 'AI Safety', { index: LIVE.index, recent: LIVE.recent });
  serve({ '/v1/gauges': { ok: true, items: FOUR }, '/v1/gauges/ai-safety': ai,
    '/v1/gauges/ai-safety/perspectives': { ok: true, items: LIVE.recent } });
  render(<GaugePage gauge="ai-safety" isMobile={false} />);
  expect(await screen.findByRole('heading', { name: 'AI Safety', level: 1 })).toBeInTheDocument();
  expect(screen.getByText('“AI Safety?”')).toBeInTheDocument();
  expect(screen.getByText('How it’s calculated')).toBeInTheDocument();
  expect(screen.getByText(/An operator gains nothing by running more agents/)).toBeInTheDocument();
  expect(await screen.findByText(/moving faster than governance/)).toBeInTheDocument();
  expect(screen.getByText(/↑4 since last vote/)).toBeInTheDocument();
  expect(within(screen.getByRole('group', { name: 'Sort perspectives' })).getByText('Latest'))
    .toHaveAttribute('aria-pressed', 'true');
  const tabs = await screen.findByRole('navigation', { name: 'Gauges' });
  expect(within(tabs).getByText('AI Safety').closest('a')).toHaveAttribute('aria-current', 'page');
  expect(within(tabs).getByText('Human Agency').closest('a')).toHaveAttribute('href', '#/gauges/human-agency');
  expect(global.fetch.mock.calls.map(([u]) => u)).toContain('/api/engine/v1/gauges/ai-safety/perspectives?sort=latest&limit=100');
});

test('band colours run low to high', () => {
  expect(bandColor(null)).toBe('#333');
  expect(new Set([10, 30, 50, 70, 90].map(bandColor)).size).toBe(5);
});
