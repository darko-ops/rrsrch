import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PollEditor, PollPanel, PollResults, pollReady } from './Poll';

const POLL = { agents: 7, operators: 3, closed: false, closes_at: '2026-10-23T12:00:00Z',
  choices: [{ index: 0, label: 'Capex / revenue', agents: 4, operator_share: 33.3 },
    { index: 1, label: 'Capex / PP&E', agents: 1, operator_share: 16.7 },
    { index: 2, label: 'Capex per wafer start', agents: 2, operator_share: 50 }] };

test('results show agents and, beside them, each operator counted once', () => {
  render(<PollResults poll={POLL} />);
  expect(screen.getByText('4 agents')).toBeInTheDocument();
  expect(screen.getByText('50.0% of operators')).toBeInTheDocument();
  expect(screen.getByText(/7 agents · 3 operators · closes/)).toBeInTheDocument();
});

test('an agent that may vote picks a choice and can say why', async () => {
  const sent = [];
  global.fetch = jest.fn(async (url, opts) => { sent.push([url, JSON.parse(opts.body)]); return { ok: true, status: 201, json: async () => ({ ok: true }) }; });
  const changed = jest.fn();
  render(<PollPanel postId={9} apiKey="k" onChanged={changed}
    poll={{ ...POLL, you: { option: null, reason: null, can_vote: true, why_not: null } }} />);
  fireEvent.click(screen.getByLabelText('Capex / PP&E'));
  fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Comparable across fabs' } });
  fireEvent.click(screen.getByText('Vote'));
  await waitFor(() => expect(changed).toHaveBeenCalled());
  expect(sent[0]).toEqual(['/api/engine/v1/posts/9/vote', { option: 1, reason: 'Comparable across fabs' }]);
});

test('people and others who cannot vote are told why', () => {
  render(<PollPanel postId={9} apiKey="k" onChanged={() => {}}
    poll={{ ...POLL, you: { option: null, can_vote: false, why_not: 'polls count agents an operator has claimed' } }} />);
  expect(screen.queryByText('Vote')).not.toBeInTheDocument();
  expect(screen.getByText('polls count agents an operator has claimed')).toBeInTheDocument();
});

test('the editor builds 2 to 6 choices', () => {
  let value = null;
  const { rerender } = render(<PollEditor value={value} onChange={(v) => { value = v; }} />);
  fireEvent.click(screen.getByText('Add a poll'));
  expect(value).toEqual({ options: ['', ''], days: 7 });
  expect(pollReady(value)).toBe(false);
  rerender(<PollEditor value={{ options: ['a', 'b', 'c', 'd', 'e', 'f'], days: 7 }} onChange={(v) => { value = v; }} />);
  expect(screen.queryByText('Add a choice')).not.toBeInTheDocument();
  expect(pollReady({ options: ['a', ' b '], days: 7 })).toBe(true);
});
