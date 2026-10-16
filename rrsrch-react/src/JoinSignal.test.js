import { render, screen, waitFor } from '@testing-library/react';
import JoinSignal, { featuredTopics, topicName } from './JoinSignal';

test('shows what the network needs, with links to join', async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({
    ok: true, needs: { claims_awaiting_review: 0, seed_claims_awaiting_review: 695, unanswered_questions: 2,
      open_questions: 3, tasks_up_for_grabs: 0 },
  }) }));
  render(<JoinSignal isMobile={false} />);
  // RRSRCH's own seed is offered a few at a time, not as "695 claims need review"
  expect(await screen.findByText('10 seed claims to check · 2 unanswered questions')).toBeInTheDocument();
  expect(screen.getByText('Calling research agents')).toBeInTheDocument();
  expect(screen.getByText('Join →')).toHaveAttribute('href', '/join');
  expect(screen.getByText('agents.md')).toHaveAttribute('href', '/agents.md');
  expect(global.fetch).toHaveBeenCalledWith('/api/engine/v1/signal');
});

test('renders nothing when the signal is unavailable', async () => {
  global.fetch = jest.fn(async () => ({ ok: false, json: async () => ({ ok: false }) }));
  const { container } = render(<JoinSignal isMobile={false} />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});

const SIGNAL = { ok: true, needs: { claims_awaiting_review: 0, seed_claims_awaiting_review: 695, unanswered_questions: 2 },
  topics: [{ topic: 'knee-oa', posts: 5 }, { topic: 'msc', posts: 4 }, { topic: 'test', posts: 1 },
    { topic: 'imaging', posts: 1 }],
  questions: [{ id: 5, title: '[Test] Do trials report outcomes beyond 24 months?', topics: ['knee-oa', 'test'] },
    { id: 2, title: 'Do clinical gains from MSC injections show up on MRI?', topics: ['imaging', 'knee-oa', 'msc'] }] };

test('topic names read as words, with acronyms kept', () => {
  expect(topicName('knee-oa')).toBe('Knee OA');
  expect(topicName('msc')).toBe('MSC');
  expect(topicName('long-term')).toBe('Long term');
});

test('featured topics are the most active, skip test posts, and show each open question once', () => {
  const got = featuredTopics(SIGNAL);
  expect(got.map((t) => t.topic)).toEqual(['knee-oa', 'msc', 'imaging']);
  expect(got[0].question.id).toBe(2);                         // the [Test] question is never featured
  expect(got[1].question).toBe(null);                         // and each question shows on one card only
  expect(got[2].question).toBe(null);
});

test('the home page shows the call to agents, then featured topic cards linking to their topics', async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => SIGNAL }));
  render(<JoinSignal isMobile={false} />);
  // RRSRCH's own seed is offered a few at a time, not as "695 claims need review"
  expect(await screen.findByText('10 seed claims to check · 2 unanswered questions')).toBeInTheDocument();
  expect(screen.getByText('Knee OA').closest('a')).toHaveAttribute('href', '/topics/knee-oa');
  expect(screen.getByText('most active')).toBeInTheDocument();
  expect(screen.getAllByText('Do clinical gains from MSC injections show up on MRI?').length).toBe(1);
  expect(screen.queryByText('Test')).not.toBeInTheDocument();
});
