import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import Dashboard from './Dashboard';
import { ReportsPage } from './Reports';

const OPEN = [
  { id: 7, target: 'post:43', repository: 'rrsrch/network', reason: 'other', detail: 'a test post', reporter: 'demetri',
    state: 'open', created_at: '2026-10-22T16:00:00Z', author: 'ominis', excerpt: 'finding: t' },
  { id: 8, target: 'message:5', repository: 'rrsrch/network', reason: 'spam', detail: '', reporter: 'lab-1',
    state: 'open', created_at: '2026-10-22T17:00:00Z', author: 'spammer', excerpt: 'buy now' },
];

function serve({ maintains = true, items = OPEN } = {}) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    const path = url.replace(/^\/api\/engine/, '');
    calls.push([opts.method || 'GET', path, opts.body ? JSON.parse(opts.body) : null]);
    let body = { ok: true };
    if (path.startsWith('/v1/reports?')) {
      const state = new URLSearchParams(path.split('?')[1]).get('state') || 'open';
      body = { ok: true, maintains, items: items.filter((r) => r.state === state) };
    } else if (path.endsWith('/resolve')) {
      const id = Number(path.split('/')[3]);
      const r = items.find((x) => x.id === id);
      r.state = JSON.parse(opts.body).action === 'hide' ? 'actioned' : 'dismissed';
      body = { ok: true, report_id: id, state: r.state };
    } else if (path === '/health') body = { ok: true, claims: 0 };
    else if (path.startsWith('/v1/repos')) body = { ok: true, items: [] };
    else if (path.startsWith('/v1/agents')) body = { ok: true, items: [] };
    else if (path === '/v1/whoami') body = { ok: true, handle: 'demetri', organization_id: 'rrsrch', org_role: 'admin', scopes: [] };
    return { ok: true, status: 200, statusText: '', json: async () => body };
  });
  return calls;
}

afterEach(() => { localStorage.clear(); window.location.hash = ''; });

test('a maintainer hides a test post or dismisses a report, with what each costs the author', async () => {
  const items = OPEN.map((r) => ({ ...r }));
  const calls = serve({ items });
  render(<ReportsPage apiKey="rrsrch_k" />);
  const first = await screen.findByRole('listitem', { name: 'Report 7' });
  expect(within(first).getByRole('link', { name: 'post:43' })).toHaveAttribute('href', '/posts/43');
  expect(first).toHaveTextContent('finding: t');
  expect(first).toHaveTextContent('“a test post”');
  expect(first).toHaveTextContent('for this reason, it costs the author nothing.');
  const spam = screen.getByRole('listitem', { name: 'Report 8' });
  expect(spam).toHaveTextContent('for spam, it costs the author 5 Sparks.');
  fireEvent.click(within(first).getByRole('button', { name: 'Hide' }));
  await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Report 7' })).toBeNull());
  expect(screen.getByRole('listitem', { name: 'Report 8' })).toHaveTextContent('buy now');
  expect(calls).toContainEqual(['POST', '/v1/reports/7/resolve', { action: 'hide' }]);
  fireEvent.click(screen.getByRole('button', { name: 'Hidden' }));
  expect(await screen.findByRole('listitem', { name: 'Report 7' })).not.toHaveTextContent('Dismiss');
});

test('Reports shows in the Agents area only to people who maintain a collection, with the open count', async () => {
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  serve({ maintains: true });
  const { unmount } = render(<Dashboard isMobile={false} initialTab="agents" />);
  const tab = await screen.findByRole('button', { name: /^Reports/ });
  expect(tab).toHaveTextContent('Reports2');
  unmount();
  serve({ maintains: false, items: [] });
  render(<Dashboard isMobile={false} initialTab="agents" />);
  expect(await screen.findByRole('button', { name: /^Tasks/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Reports/ })).toBeNull();
});
