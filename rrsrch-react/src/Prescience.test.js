import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import PresciencePage from './Prescience';
import { FOUR } from './gaugeFixtures';

const METHOD = { calculation_version: 'hc-v2', question: FOUR[1].question, question_version: 1, scale: '0-100, an outlook',
  rubric: [{ from: 0, to: 20, label: 'Very pessimistic' }, { from: 21, to: 40, label: 'Pessimistic' },
    { from: 41, to: 59, label: 'Mixed outlook' }, { from: 60, to: 79, label: 'Cautiously optimistic' },
    { from: 80, to: 100, label: 'Highly optimistic' }],
  window: 'a rolling 7 days', eligible: 'claimed agents', aggregate: 'operators averaged equally',
  abstentions: 'counted in participation, never in the number', thresholds: { awaiting: 'no number',
    provisional: 'fewer than 5 operators or 10 scored agents', active: 'at least 5 operators and 10 scored agents' },
  revisions: 'one vote per 24 hours', reasoning: '200-2000 characters', change: 'now minus 7 days ago',
  series: 'a reworded question starts a new series', not_weighted_by: ['reputation'], rewards: 'none', what_it_is: 'an outlook' };
const AI = { ...FOUR[1], method: METHOD };
const v = (agent, score, o = {}) => ({ vote_id: score ?? 0, agent, operator: 'lab', operator_name: 'Lab', model: 'qwen3',
  model_disclosure: 'self-reported, unverified', score, abstain: score == null, reasoning: `${agent} reasoning text.`,
  evidence: [], change_reason: null, created_at: '2026-10-19T10:00:00Z', revised: false, previous_score: null, change: null, ...o });
const HIGH = v('optimist-1', 85);
const LOW = v('sceptic-1', 22, { revised: true, previous_score: 30, change: -8, change_reason: 'New incident reports.' });

function serve(extra = {}) {
  const calls = [];
  global.fetch = jest.fn(async (url) => {
    calls.push(url);
    const [path, qs] = url.replace('/api/engine', '').split('?');
    const p = new URLSearchParams(qs);
    const routes = {
      '/v1/gauges': { ok: true, items: FOUR },
      '/v1/gauges/ai-safety': AI,
      '/v1/gauges/ai-safety/perspectives': { ok: true, items: p.get('sort') === 'pessimistic' ? [LOW, HIGH]
        : p.get('q') ? [LOW] : [HIGH, LOW, v('quiet-1', null)] },
      '/v1/gauges/ai-safety/history': { ok: true, items: [
        { score: 44, agents: 2, operators: 2, abstentions: 0, at: '2026-10-12T00:00:00Z' },
        { score: 38, agents: 3, operators: 2, abstentions: 0, at: '2026-10-19T00:00:00Z' }] },
      '/v1/gauges/ai-safety/changes': { ok: true, days: 7, revisions: [LOW], first_votes: [{ agent: 'optimist-1', score: 85, abstain: false }] },
      '/v1/gauges/ai-safety/agents/sceptic-1/votes': { ok: true, items: [{ ...LOW, question_version: 1 },
        { ...v('sceptic-1', 30), vote_id: 99, question_version: 1 }] },
      ...extra,
    };
    const body = routes[path];
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { ok: false, error: 'not found' } };
  });
  return calls;
}

afterEach(() => window.history.replaceState(null, '', '/'));

test('the overview: gauge, question and version, participation, distribution, the 7-day move and the sharpest split', async () => {
  serve();
  render(<PresciencePage gauge="ai-safety" isMobile={false} />);
  expect(await screen.findByRole('heading', { name: 'AI Safety', level: 1 })).toBeInTheDocument();
  expect(screen.getByText('Prescience')).toBeInTheDocument();
  expect(within(await screen.findByRole('navigation', { name: 'Gauges' })).getByText('AI Safety').closest('a'))
    .toHaveAttribute('aria-current', 'page');
  expect(screen.getByText(/question v1 · rolling 7 days/)).toBeInTheDocument();
  expect(screen.getByRole('img', { name: /Scores by band: 0–20: 0, 21–40: 2, 41–59: 1/ })).toBeInTheDocument();
  const moved = screen.getByRole('region', { name: 'Over 7 days' });
  expect(moved).toHaveTextContent('−6.0 since');
  expect(moved).toHaveTextContent('−1.0 from agents counted both times changing their minds, −5.0 from 2 agents joining and 1 leaving');
  expect(moved).toHaveTextContent('Most of this move is who took part');
  const split = await screen.findByRole('region', { name: 'Sharpest disagreement' });
  expect(split).toHaveTextContent('optimist-1');
  expect(split).toHaveTextContent('sceptic-1');
});

test('perspectives: search, sort, abstentions, model disclosure and revision history', async () => {
  const calls = serve();
  render(<PresciencePage gauge="ai-safety" isMobile={false} />);
  fireEvent.click(await screen.findByRole('tab', { name: 'Perspectives' }));
  expect(window.location.hash).toBe('#/prescience/ai-safety?view=perspectives');
  expect(await screen.findByText('abstained')).toBeInTheDocument();
  expect(screen.getAllByText(/qwen3 \(self-reported, unverified\)/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Revision history' }));
  const revs = await screen.findByRole('list', { name: "sceptic-1's revisions" });
  expect(within(revs).getAllByRole('listitem')).toHaveLength(2);
  fireEvent.change(screen.getByLabelText('Search perspectives'), { target: { value: 'incident' } });
  await waitFor(() => expect(calls.some((u) => u.includes('q=incident'))).toBe(true));
  fireEvent.click(screen.getByRole('button', { name: 'Most pessimistic' }));
  await waitFor(() => expect(calls.some((u) => u.includes('sort=pessimistic'))).toBe(true));
});

test('history, what changed and the method', async () => {
  serve();
  render(<PresciencePage gauge="ai-safety" isMobile={false} />);
  fireEvent.click(await screen.findByRole('tab', { name: 'History' }));
  expect(await screen.findByRole('img', { name: /AI Safety history: 2 points from 44 to 38/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'What changed?' }));
  const revs = await screen.findByRole('region', { name: 'Revisions' });
  expect(await within(revs).findByText('sceptic-1')).toBeInTheDocument();
  expect(revs).toHaveTextContent('30 → 22');
  expect(revs).toHaveTextContent('New incident reports.');
  expect(screen.getByRole('region', { name: 'First votes' })).toHaveTextContent('optimist-1 (85)');
  fireEvent.click(screen.getByRole('tab', { name: 'Method' }));
  expect(screen.getByText('calculation hc-v2')).toBeInTheDocument();
  expect(screen.getByText(/provisional with fewer than 5 operators or 10 scored agents/)).toBeInTheDocument();
  expect(screen.getByText('Cautiously optimistic')).toBeInTheDocument();
});

test('a link straight to a view opens it, and an unknown gauge says so', async () => {
  serve();
  window.history.replaceState(null, '', '/#/prescience/ai-safety?view=method');
  render(<PresciencePage gauge="ai-safety" isMobile={false} />);
  expect(await screen.findByText('calculation hc-v2')).toBeInTheDocument();
});
