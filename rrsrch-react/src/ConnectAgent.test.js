import { render, screen, fireEvent } from '@testing-library/react';
import ConnectAgent, { setupFor, CLIENTS } from './ConnectAgent';

const KEY = 'rrsrch_abc123_secret';

function serve(whoami, calls = []) {
  global.fetch = jest.fn((url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    const body = opts.body ? JSON.parse(opts.body) : null;
    calls.push([opts.method || 'GET', path, body]);
    const ok = (d) => Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ ok: true, ...d }) });
    if (path === '/v1/whoami') {
      const w = whoami();
      if (!w) return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({ ok: false, error: 'authentication required' }) });
      return ok(w);
    }
    if (path === '/v1/organizations') return ok({ organization: { id: 'harbor-lab' } });
    if (path === '/v1/agents/connect') {
      return ok({ agent: { handle: body.handle, organization_id: 'harbor-lab' }, key: KEY, scopes: ['propose', 'read', 'review'] });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ ok: false, error: 'not found' }) });
  });
  return calls;
}

const USER = { email: 'x@example.org', email_verified: true };
afterEach(() => localStorage.clear());

test('every client gets a setup with the key in it', () => {
  for (const [id] of CLIENTS) expect(setupFor(id, KEY).text).toContain(`Bearer ${KEY}`);
  expect(setupFor('claude-code', KEY).text).toBe(
    `claude mcp add --transport http --scope user rrsrch https://rrsrch.com/mcp --header "Authorization: Bearer ${KEY}"`);
  expect(JSON.parse(setupFor('cursor', KEY).text).mcpServers.rrsrch.url).toBe('https://rrsrch.com/mcp');
  expect(JSON.parse(setupFor('claude-desktop', KEY).text).mcpServers.rrsrch.env.RRSRCH_AUTH).toBe(`Bearer ${KEY}`);
  expect(setupFor('codex', KEY).text).toContain('[mcp_servers.rrsrch]');
});

test('signed out, it asks you to sign in first', () => {
  serve(() => ({}));
  render(<ConnectAgent user={null} isMobile={false} onSignedIn={() => {}} />);
  expect(screen.getByText(/Sign in or create an account first/)).toBeInTheDocument();
});

test('a person with no organization names one, picks a client and gets one command with the key', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  let org = 'people';
  // new to the engine: whoami is a 401 until their first write, the organization
  const calls = serve(() => (org === 'people' ? null : { handle: 'dana', organization_id: org, org_role: 'admin' }));
  render(<ConnectAgent user={USER} isMobile={false} />);
  fireEvent.change(await screen.findByLabelText('organization name'), { target: { value: 'Harbor Lab' } });
  org = 'harbor-lab';
  fireEvent.click(screen.getByRole('button', { name: 'Create it' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Cursor' }));
  expect(screen.getByLabelText('agent handle')).toHaveValue('harbor-lab-cursor');
  fireEvent.click(screen.getByRole('button', { name: 'Claude Code' }));
  expect(screen.getByLabelText('agent handle')).toHaveValue('harbor-lab-claude');
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  expect(await screen.findByText('harbor-lab-claude is connected')).toBeInTheDocument();
  expect(screen.getByText(/claude mcp add --transport http --scope user rrsrch/)).toHaveTextContent(KEY);
  expect(screen.getByText(/not shown again/)).toBeInTheDocument();
  const writes = calls.filter(([m]) => m === 'POST').map(([, p, b]) => [p, b]);
  expect(writes).toEqual([
    ['/v1/organizations', { id: 'harbor-lab', name: 'Harbor Lab' }],
    ['/v1/agents/connect', { handle: 'harbor-lab-claude', client: 'claude-code', model: null }],
  ]);
});

test('a member who is not an admin is told to ask one', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  serve(() => ({ handle: 'dana', organization_id: 'harbor-lab', org_role: 'member' }));
  render(<ConnectAgent user={USER} isMobile={false} />);
  expect(await screen.findByText(/not an admin/)).toBeInTheDocument();
});
