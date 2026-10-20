import { render, screen, within } from '@testing-library/react';
import GaugeRow, { bandColor, shown } from './HumanityConfidence';
import { FOUR, Q } from './gaugeFixtures';

function serve(byPath) {
  global.fetch = jest.fn(async (url) => {
    const path = url.replace('/api/engine', '').split('?')[0];
    const body = byPath[path];
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { ok: false, error: 'not found' } };
  });
}

test('the Network page shows four gauges, each opening its Prescience page', async () => {
  serve({ '/v1/gauges': { ok: true, items: FOUR } });
  render(<GaugeRow isMobile={false} />);
  const row = await screen.findByRole('region', { name: 'Gauges' });
  const cards = await within(row).findAllByRole('link', { name: /^Open / });
  expect(cards.map((a) => a.getAttribute('href'))).toEqual(['#/prescience/humanity-confidence', '#/prescience/ai-safety',
    '#/prescience/scientific-progress', '#/prescience/human-agency']);
  expect(cards[0]).toHaveTextContent('68.4');
  expect(cards[0]).toHaveTextContent('+2.3 over 7 days');
  expect(cards[0]).not.toHaveTextContent('Provisional');                              // active: 6 operators, 12 agents
  expect(cards[0]).toHaveTextContent('12 agents · 6 operators · 2 abstained');
  expect(cards[1]).toHaveTextContent('Provisional · 2 operators');
  expect(cards[1]).toHaveTextContent('−6.0 over 7 days');
  expect(cards[1]).toHaveTextContent('mostly agents joining or leaving');
  expect(cards[2]).toHaveTextContent('Awaiting agent perspectives.');                 // only an abstention: no number
  expect(cards[2]).toHaveTextContent('1 abstained');
  expect(within(cards[3]).getByRole('img', { name: 'Human Agency gauge: no score yet' })).toBeInTheDocument();
  expect(cards[0]).toHaveAttribute('title', Q);
  expect(within(row).getByText('All gauges →')).toHaveAttribute('href', '#/radar');
  expect(row).toHaveTextContent(/not a measurement or a verified prediction/);
});

test('a gauge shows a number only when agents have scored', () => {
  expect(shown(FOUR[0]).score).toBe(68.4);
  expect(shown(FOUR[2])).toBe(null);
  expect(shown(FOUR[3])).toBe(null);
});

test('the row renders nothing when the engine is unavailable', async () => {
  serve({});
  const { container } = render(<GaugeRow isMobile={false} />);
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});

test('band colours run low to high', () => {
  expect(bandColor(null)).toBe('#333');
  expect(new Set([10, 30, 50, 70, 90].map(bandColor)).size).toBe(5);
});
