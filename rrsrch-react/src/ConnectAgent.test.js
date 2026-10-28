import { render, screen, fireEvent } from '@testing-library/react';
import ConnectAgent, { FIRST_PROMPT, MCP_URL } from './ConnectAgent';

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

test('every agent gets the same prompt, which reads the key from the environment and never holds it', () => {
  expect(FIRST_PROMPT).toContain('https://rrsrch.com/agents.md');
  expect(FIRST_PROMPT).toContain('$RRSRCH_KEY');
  expect(MCP_URL).toBe('https://rrsrch.com/mcp');
});

test('signed out, it asks you to sign in first', () => {
  serve(() => ({}));
  render(<ConnectAgent user={null} isMobile={false} onSignedIn={() => {}} />);
  expect(screen.getByText(/Sign in or create an account first/)).toBeInTheDocument();
});

test('a person with no organization names one and gets the key and the one prompt', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  let org = 'people';
  // new to the engine: whoami is a 401 until their first write, the organization
  const calls = serve(() => (org === 'people' ? null : { handle: 'dana', organization_id: org, org_role: 'admin' }));
  render(<ConnectAgent user={USER} isMobile={false} />);
  fireEvent.change(await screen.findByLabelText('organization name'), { target: { value: 'Harbor Lab' } });
  org = 'harbor-lab';
  fireEvent.click(screen.getByRole('button', { name: 'Create it' }));
  expect(await screen.findByLabelText('agent handle')).toHaveValue('harbor-lab-agent');
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  expect(await screen.findByText('harbor-lab-agent is connected')).toBeInTheDocument();
  expect(screen.getByText(KEY)).toBeInTheDocument();                  // the key alone, to paste anywhere
  expect(screen.getByText(FIRST_PROMPT)).toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'MCP client' })).toBeNull();
  expect(screen.getByText(/not shown again/)).toBeInTheDocument();
  const writes = calls.filter(([m]) => m === 'POST').map(([, p, b]) => [p, b]);
  expect(writes).toEqual([
    ['/v1/organizations', { id: 'harbor-lab', name: 'Harbor Lab' }],
    ['/v1/agents/connect', { handle: 'harbor-lab-agent', client: 'other', model: null }],
  ]);
});

test('a member who is not an admin is told to ask one', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  serve(() => ({ handle: 'dana', organization_id: 'harbor-lab', org_role: 'member' }));
  render(<ConnectAgent user={USER} isMobile={false} />);
  expect(await screen.findByText(/not an admin/)).toBeInTheDocument();
});
