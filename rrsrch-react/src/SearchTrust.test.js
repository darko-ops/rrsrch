import { render, screen, fireEvent } from '@testing-library/react';
import SearchExperience from './SearchExperience';

const REPORT = {
  ok: true, engine: 'rrsrch', question: 'q', verdict: 'benefit', headline: 'Benefit: the claims favour MSCs.',
  kicker: 'Answer from 2 findings in 2 studies',
  sentences: [{ text: 'VAS pain was lower with MSCs at 12 months.', cites: ['7', '8'] }],
  citations: {
    7: { text: 'VAS pain was lower with MSCs (p = 0.01).', src: 'Trial A', verdict: 'benefit', url: null, claim_id: 7,
      repository: 'rrsrch/msc-knee-oa', state: 'supported', version: 2, open_challenges: 0, contradicted_by: [8] },
    8: { text: 'VAS pain did not differ.', src: 'Trial B', verdict: 'no_difference', url: null, claim_id: 8,
      repository: 'rrsrch/msc-knee-oa', state: 'structurally_valid', version: 1, open_challenges: 1, contradicted_by: [7] },
  },
  trust: { claims: 2, by_state: { supported: 1, structurally_valid: 1 }, challenged: 1, contradicted: 2 },
  groups: [], gaps: null, engineLive: true,
};

test('answers show where their claims stand in review, down to each citation', async () => {
  global.fetch = jest.fn(async (url) => ({
    ok: true, status: 200,
    json: async () => (url.includes('/api/engine/answer') ? REPORT : { results: [], suggestions: [] }),
  }));
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} onAgents={() => {}} />);
  fireEvent.change(screen.getByPlaceholderText(/Ask a question/), { target: { value: 'Does MSC reduce pain?' } });
  fireEvent.submit(screen.getByPlaceholderText(/Ask a question/).closest('form'));
  expect(await screen.findByText(/Rests on 2 claims/)).toBeInTheDocument();
  expect(screen.getByText('1 supported')).toBeInTheDocument();
  expect(screen.getByText('1 under challenge')).toBeInTheDocument();

  fireEvent.click(screen.getAllByRole('button', { name: /7/ })[0]);
  expect(await screen.findByText('Supported')).toBeInTheDocument();
  expect(screen.getByText(/Trace in Atlas/).closest('a').getAttribute('href'))
    .toBe('#/agents?tab=atlas&repo=rrsrch%2Fmsc-knee-oa&claim=7');
  fireEvent.click(screen.getByText('finding 8'));                 // jump to the contradicting finding
  expect(await screen.findByText('Unreviewed')).toBeInTheDocument();
  expect(screen.getByText('1 open challenge')).toBeInTheDocument();
});
