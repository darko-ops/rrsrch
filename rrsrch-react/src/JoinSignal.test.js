import { render, screen, waitFor } from '@testing-library/react';
import JoinSignal from './JoinSignal';

test('shows what the network needs, with links to join', async () => {
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({
    ok: true, needs: { claims_awaiting_review: 695, unanswered_questions: 2, open_questions: 3, tasks_up_for_grabs: 0 },
  }) }));
  render(<JoinSignal isMobile={false} />);
  expect(await screen.findByText('695 claims need review · 2 unanswered questions')).toBeInTheDocument();
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
