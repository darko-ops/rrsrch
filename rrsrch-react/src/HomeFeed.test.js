import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import { GaugeStrip, HomeFeed } from './HomeFeed';

const gauge = (slug, title, core, score, change = null) => ({ gauge: slug, title, core, question: `${title}?`,
  index: score == null ? { status: 'awaiting', score: null } : { status: 'provisional', score, agents: 3, operators: 2 },
  change_7d: change == null ? null : { change } });
const GAUGES = { ok: true, items: [gauge('humanity-confidence', 'Humanity Confidence', true, 68.4, 2.3),
  gauge('ai-safety', 'AI Safety', true, 38, -6), gauge('human-agency', 'Human Agency', true, null),
  gauge('compute-abundance', 'Compute Abundance', false, 48.5)] };
const FEED = { ok: true, next_offset: 10, kind_counts: { question: 1, finding: 0 }, items: [
  { id: 4, repository: 'rrsrch/network', author: 'ext', author_kind: 'human', kind: 'question', status: 'open',
    title: 'Does the effect hold past 24 months?', excerpt: 'Looking for long follow-up.', topics: ['msc'],
    created_at: '2026-10-14T00:00:00Z', comments: 0, reports: 0, author_claimed: true, evidence: 0 }] };

function mock(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url) => {
    calls.push(url);
    const hit = Object.keys(routes).find((k) => url.includes(k));
    const body = hit ? routes[hit] : null;
    return { ok: !!body, status: body ? 200 : 500, json: async () => body || { ok: false, error: 'down' } };
  });
  return calls;
}

afterEach(() => localStorage.clear());

test('the core gauges show in a row, each linking to its page; other gauges stay on the Radar', async () => {
  mock({ '/v1/gauges': GAUGES });
  render(<GaugeStrip isMobile={false} />);
  const strip = await screen.findByRole('region', { name: 'Core gauges' });
  const cards = await within(strip).findAllByRole('link', { name: /:/ });
  expect(cards.map((a) => a.getAttribute('aria-label'))).toEqual(['Humanity Confidence: 68.4', 'AI Safety: 38.0',
    'Human Agency: no score yet']);
  expect(cards[0]).toHaveAttribute('href', '#/prescience/humanity-confidence');
  expect(within(cards[0]).getByText('+2.3')).toBeInTheDocument();
  expect(within(cards[1]).getByText('−6.0')).toBeInTheDocument();
  expect(within(cards[2]).getByText('No score yet')).toBeInTheDocument();
  expect(within(strip).getByText('Radar →')).toHaveAttribute('href', '#/radar');
});

test('the gauge strip hides when the engine can\'t say', async () => {
  mock({});
  const { container } = render(<GaugeStrip isMobile={false} />);
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});

test('the home feed loads the newest ten, filters like the Network page, and links to it', async () => {
  const calls = mock({ '/v1/explore': FEED });
  render(<HomeFeed isMobile={false} stickyTop={93} />);
  expect(await screen.findByRole('heading', { name: 'Does the effect hold past 24 months?' })).toBeInTheDocument();
  expect(calls[0]).toBe('/api/engine/v1/explore?sort=recent&limit=10');
  fireEvent.click(screen.getByRole('tab', { name: 'Unanswered' }));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls).toContain('/api/engine/v1/explore?sort=recent&limit=10&unanswered=true');
  expect(screen.queryByRole('tab', { name: 'Following' })).not.toBeInTheDocument();      // signed out
  expect(screen.getByText('Open Network →')).toHaveAttribute('href', '#/explore');
  fireEvent.click(screen.getByText('Show more'));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls).toContain('/api/engine/v1/explore?sort=recent&limit=20&unanswered=true');
});
