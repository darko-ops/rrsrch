import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { IssueKeyForm, KeysList } from './Dashboard';

function serve(byPath) {
  global.fetch = jest.fn(async (url, opts) => {
    const body = byPath[url.replace('/api/engine', '')];
    return { ok: true, status: 200, json: async () => (typeof body === 'function' ? body(opts) : body) };
  });
}

test('a new key stays valid while used unless a fixed lifetime is chosen', async () => {
  const sent = [];
  serve({ '/v1/agents/bot/keys': (opts) => { sent.push(JSON.parse(opts.body)); return { ok: true, key: 'k', scopes: ['read'] }; } });
  const issued = jest.fn();
  render(<IssueKeyForm apiKey="x" handle="bot" ownScopes={null} onIssued={issued} />);
  fireEvent.click(screen.getByText('Issue key'));
  await waitFor(() => expect(issued).toHaveBeenCalled());
  expect(sent[0]).toEqual({ scopes: ['read'], label: '' });                      // no days: valid while used

  fireEvent.change(screen.getByLabelText('Lifetime'), { target: { value: 'fixed' } });
  fireEvent.change(screen.getByDisplayValue('30'), { target: { value: '7' } });
  fireEvent.click(screen.getByText('Issue key'));
  await waitFor(() => expect(sent).toHaveLength(2));
  expect(sent[1]).toEqual({ scopes: ['read'], label: '', days: 7 });
});

test('the key list says which keys live while used', async () => {
  const later = new Date(Date.now() + 80 * 864e5).toISOString();
  serve({ '/v1/agents/bot/keys': { ok: true, keys: [
    { id: 1, prefix: 'aaaaaaaaaaaa', scopes: ['read'], label: 'loop', expires_at: later, idle_days: 90, last_used_at: later },
    { id: 2, prefix: 'bbbbbbbbbbbb', scopes: ['read'], label: 'one-off', expires_at: later, idle_days: null } ] } });
  render(<KeysList apiKey="x" handle="bot" canManage={false} />);
  expect(await screen.findByText(/valid while used · ends .* if unused/)).toBeInTheDocument();
  expect(screen.getByText(/^expires /)).toBeInTheDocument();
});
