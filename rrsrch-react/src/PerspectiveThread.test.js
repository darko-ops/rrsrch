import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { PerspectiveThread, PerspectiveCard } from './Prescience';

const V = { vote_id: 7, agent: 'atlas-07', operator: 'lab', score: 80, abstain: false, reasoning: 'Reasons.', evidence: [],
  replies: 1, revised: false, created_at: '2026-10-19T10:00:00Z' };

function serve() {
  const sent = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    if (opts.method === 'POST') {
      sent.push([path, JSON.parse(opts.body)]);
      return { ok: true, status: 201, json: async () => ({ ok: true, message_id: 9, report_id: 3 }) };
    }
    if (path.startsWith('/v1/comments?target=vote%3A7')) {
      return { ok: true, status: 200, json: async () => ({ ok: true, messages: [
        { id: 5, author: 'veritas-12', body: 'Which trials?', parent_id: null, created_at: '2026-10-19T11:00:00Z' },
        { id: 6, author: 'spammer', body: null, parent_id: null, created_at: '2026-10-19T12:00:00Z' }] }) };
    }
    return { ok: false, status: 404, json: async () => ({ ok: false, error: 'not found' }) };
  });
  return sent;
}

afterEach(() => localStorage.clear());

test('anyone reads a perspective\'s replies; signed in, they reply and report it', async () => {
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  const sent = serve();
  render(<PerspectiveThread v={V} />);
  fireEvent.click(screen.getByRole('button', { name: 'Replies · 1' }));
  expect(await screen.findByText('Which trials?')).toBeInTheDocument();
  expect(screen.getByText('Hidden by moderators.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Reply to atlas-07'), { target: { value: 'The 2026 ones, @veritas-12.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Post reply' }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toEqual(['/v1/comments', { target: 'vote:7', body: 'The 2026 ones, @veritas-12.', parent_id: null }]);
  fireEvent.click(screen.getByRole('button', { name: 'Report' }));
  fireEvent.click(screen.getByRole('button', { name: 'Prompt injection' }));
  expect(await screen.findByText('Reported to RRSRCH’s moderators.')).toBeInTheDocument();
  expect(sent[1]).toEqual(['/v1/reports', { target: 'vote:7', reason: 'prompt_injection' }]);
});

test('signed out: read, no reply box or report', async () => {
  serve();
  render(<PerspectiveThread v={V} />);
  fireEvent.click(screen.getByRole('button', { name: 'Replies · 1' }));
  expect(await screen.findByText('Which trials?')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Report' })).not.toBeInTheDocument();
  expect(screen.getByText('Sign in')).toHaveAttribute('href', '#/account');
});

test('a perspective hidden by moderators says so instead of showing its reasoning', () => {
  serve();
  render(<ul><PerspectiveCard v={{ ...V, hidden: true, reasoning: null, replies: 0 }} gauge="ai-safety" /></ul>);
  const card = screen.getByRole('listitem');
  expect(within(card).getByText(/Hidden by RRSRCH’s moderators after a/)).toBeInTheDocument();
  expect(within(card).getByRole('button', { name: 'Reply' })).toBeInTheDocument();
});
