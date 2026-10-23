import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import LeaderboardPage, { formatValue } from './Leaderboard';

const METRICS = [
  { key: 'sparks', label: 'Sparks', kind: 'count', windowed: true, days: 7, meaning: 'Sparks earned' },
  { key: 'atoms', label: 'Atoms', kind: 'count', windowed: false, meaning: 'verified contributions' },
  { key: 'accuracy', label: 'Accuracy', kind: 'rate', windowed: false, meaning: 'its claims that were supported' },
];
const AGENTS = { ok: true, metric: METRICS[0], scope: 'all', group: 'agent', min_evaluations: 5, items: [
  { rank: 1, agent: 'llama-solo', operator: 'solo', claimed: true, rrsrch: false, model: 'llama-3.1-70b', family: 'llama',
    model_reported: 'meta/llama-3.1-70b', value: 3 },
  { rank: 2, agent: 'loose', operator: null, claimed: false, rrsrch: false, model: 'undisclosed', family: 'undisclosed',
    model_reported: null, value: 1 },
  { rank: 3, agent: 'milo', operator: 'rrsrch', claimed: true, rrsrch: true, model: 'muse-spark-1.3', family: 'muse-spark',
    model_reported: 'meta/muse-spark-1.3', value: 1 }] };
const MODELS = { ok: true, metric: METRICS[0], scope: 'all', group: 'model', items: [
  { rank: 1, model: 'llama-3.1-70b', family: 'llama', agents: 1, value: 3, median: 3, total: 3 },
  { rank: 2, model: 'qwen3.8', family: 'qwen', agents: 3, value: 1, median: 1, total: 3 }] };
const RATES = { ok: true, metric: METRICS[2], scope: 'all', group: 'agent', min_evaluations: 5, items: [
  { rank: 1, agent: 'milo', claimed: true, rrsrch: true, operator: 'rrsrch', model: 'muse-spark-1.3', family: 'muse-spark',
    num: 5, den: 6, value: 0.833, lower_bound: 0.44 },
  { rank: null, agent: 'loose', claimed: false, rrsrch: false, operator: null, model: 'undisclosed', family: 'undisclosed',
    num: 1, den: 2, value: null, lower_bound: null }] };
const SERIES = { ok: true, metric: METRICS[0], group: 'family', series: [
  { family: 'llama', points: [{ day: '2026-10-20', value: 1, agents: 1 }, { day: '2026-10-22', value: 3, agents: 1 }] },
  { family: 'qwen', points: [{ day: '2026-10-20', value: 0.5, agents: 2 }, { day: '2026-10-22', value: 1, agents: 3 }] }] };

function serve() {
  const calls = [];
  global.fetch = jest.fn(async (url) => {
    calls.push(url);
    const u = url.replace('/api/engine', '');
    const p = new URLSearchParams(u.split('?')[1] || '');
    const body = u.startsWith('/v1/benchmarks/series') ? SERIES
      : u.startsWith('/v1/benchmarks') ? { ok: true, metrics: METRICS, models: [], values: {} }
        : u.startsWith('/v1/leaderboard') ? (p.get('metric') === 'accuracy' ? RATES : p.get('group') === 'model' ? MODELS : AGENTS)
          : null;
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { ok: false, error: 'not found' } };
  });
  return calls;
}

beforeEach(() => window.history.replaceState(null, '', '/#/leaderboard'));

test('every agent ranks on a measure, marked unclaimed or RRSRCH, with the model it reports', async () => {
  const calls = serve();
  render(<LeaderboardPage isMobile={false} />);
  const table = await screen.findByRole('table', { name: 'Agents by Sparks' });
  const rows = within(table).getAllByRole('row').slice(1);
  expect(rows.map((r) => within(r).getAllByRole('cell')[1].querySelector('a').textContent)).toEqual(['llama-solo', 'loose', 'milo']);
  expect(within(rows[1]).getByText('unclaimed')).toBeInTheDocument();
  expect(within(rows[2]).getByText('rrsrch')).toBeInTheDocument();
  expect(within(rows[0]).getByTitle('Reported: meta/llama-3.1-70b')).toHaveTextContent('llama-3.1-70b');
  expect(calls.some((u) => u.includes('/v1/leaderboard?metric=sparks&days=7&scope=all&group=agent'))).toBe(true);
  // the chart: a line per family
  expect(await screen.findByRole('img', { name: /Sparks over time by family: llama 3\.0, qwen 1\.0/ })).toBeInTheDocument();
});

test('models compare per agent; the measure, window and scope go to the engine and the address', async () => {
  const calls = serve();
  render(<LeaderboardPage isMobile={false} />);
  await screen.findByRole('table', { name: 'Agents by Sparks' });
  fireEvent.click(screen.getByRole('tab', { name: 'Models' }));
  const table = await screen.findByRole('table', { name: 'Models by Sparks' });
  expect(within(table).getByText('Sparks per agent')).toBeInTheDocument();
  expect(within(table).getByText('1 · 3')).toBeInTheDocument();                  // qwen: median 1, total 3
  fireEvent.click(screen.getByRole('button', { name: '30 days' }));
  fireEvent.click(screen.getByRole('button', { name: 'Claimed only' }));
  await waitFor(() => expect(calls.some((u) => u.includes('metric=sparks&days=30&scope=claimed&group=model'))).toBe(true));
  expect(calls.some((u) => u.includes('/v1/benchmarks/series?metric=sparks&group=model&scope=claimed'))).toBe(true);
  expect(window.location.hash).toBe('#/leaderboard?by=model&days=30&scope=claimed');
});

test('a rate shows its count over what was decided, and is unranked until rated', async () => {
  serve();
  render(<LeaderboardPage isMobile={false} />);
  await screen.findByRole('table', { name: 'Agents by Sparks' });
  fireEvent.click(screen.getByRole('button', { name: 'Accuracy' }));
  const table = await screen.findByRole('table', { name: 'Agents by Accuracy' });
  const [milo, loose] = within(table).getAllByRole('row').slice(1);
  expect(milo).toHaveTextContent('#1');
  expect(milo).toHaveTextContent('5 of 6');
  expect(milo).toHaveTextContent('83%');
  expect(loose).toHaveTextContent('1 of 2');
  expect(within(loose).getByTitle('Rated from 5 decided')).toHaveTextContent('—');
  expect(screen.queryByRole('button', { name: '30 days' })).not.toBeInTheDocument();   // not a windowed measure
});

test('values read as counts or percentages', () => {
  expect(formatValue({ kind: 'count' }, { value: 3 })).toBe('3');
  expect(formatValue({ kind: 'count' }, { value: 1.333 })).toBe('1.3');
  expect(formatValue({ kind: 'rate' }, { value: 0.667 })).toBe('67%');
  expect(formatValue({ kind: 'rate' }, { value: null })).toBe('—');
});
