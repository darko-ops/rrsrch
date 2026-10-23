import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AccountSignedOut, AccountSignedIn, PasswordUpgrade } from './AccountPages';

function mock(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const key = Object.keys(routes).find((k) => {
      const [method, path] = k.includes(' ') ? k.split(' ') : [null, k];
      return url.includes(path) && (!method || (opts.method || 'GET') === method);
    });
    const hit = key ? routes[key] : { ok: true, body: {} };
    return { ok: hit.ok !== false, status: hit.status || (hit.ok === false ? 400 : 200), json: async () => hit.body };
  });
  return calls;
}
const settle = () => new Promise((r) => setTimeout(r, 0));
const USER = { id: 'u1', name: 'Ada Lovelace', email: 'ada@x.test', email_verified: true, google: false, has_password: true };
const ME = { handle: 'ada-lovelace', organization_id: 'people', org_role: 'member', scopes: ['read'] };

afterEach(() => localStorage.clear());

test('signing in posts the credentials and stores the account token', async () => {
  const calls = mock({ '/api/account/login': { body: { token: 'tok.1', user: USER } }, '/api/account/config': { body: {} } });
  const signedIn = jest.fn();
  render(<AccountSignedOut isMobile={false} onSignedIn={signedIn} onKey={jest.fn()} />);
  expect(screen.getByText('Sign in to work on the network')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@x.test' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'whatever' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await waitFor(() => expect(signedIn).toHaveBeenCalledWith(USER));
  expect(JSON.parse(calls.find((c) => c.url === '/api/account/login').opts.body)).toEqual({ email: 'ada@x.test', password: 'whatever' });
  expect(localStorage.getItem('rrsrch_token')).toBe('tok.1');
});

test('creating an account shows the password rules and waits until they pass', async () => {
  mock({ '/api/account/config': { body: {} } });
  render(<AccountSignedOut isMobile={false} onSignedIn={jest.fn()} onKey={jest.fn()} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Create account' }));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada' } });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@x.test' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'short' } });
  expect(screen.getByLabelText('password requirements')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Create account' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-Horse-battery-7' } });
  expect(screen.getByRole('button', { name: 'Create account' })).toBeEnabled();
});

test('connecting an agent key checks it with the engine and keeps it in this browser', async () => {
  const calls = mock({ '/v1/whoami': { body: { ok: true, handle: 'scout' } }, '/api/account/config': { body: {} } });
  const onKey = jest.fn();
  render(<AccountSignedOut isMobile={false} onSignedIn={jest.fn()} onKey={onKey} />);
  expect(screen.getByText('Read https://rrsrch.com/agents.md and follow it to join RRSRCH.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('agent key'), { target: { value: ' rrsrch_abc ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(onKey).toHaveBeenCalled());
  expect(calls.find((c) => c.url.includes('/v1/whoami')).opts.headers.Authorization).toBe('Bearer rrsrch_abc');
  expect(localStorage.getItem('rrsrch_engine_key')).toBe('rrsrch_abc');
});

test('a rejected key is not stored', async () => {
  mock({ '/v1/whoami': { ok: false, status: 401, body: { ok: false, error: 'invalid key' } }, '/api/account/config': { body: {} } });
  render(<AccountSignedOut isMobile={false} onSignedIn={jest.fn()} onKey={jest.fn()} />);
  fireEvent.change(screen.getByLabelText('agent key'), { target: { value: 'rrsrch_bad' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  expect(await screen.findByText(/not accepted/)).toBeInTheDocument();
  expect(localStorage.getItem('rrsrch_engine_key')).toBeNull();
});

test('signed in: the identity card shows standing, and Save updates the name and the About text', async () => {
  localStorage.setItem('rrsrch_token', 'tok.1');
  const calls = mock({
    '/standing': { body: { ok: true, impetus: { outcomes: [
      { metric: 'accuracy', count: 2, of: 2 }, { metric: 'review_judgement', count: 3, of: 5 }] },
      sparks: { available: 60 } } },
    'PATCH /v1/agents/ada-lovelace': { body: { ok: true, agent: { description: 'Reviews dosing.' } } },
    'GET /v1/agents/ada-lovelace': { body: { ok: true, agent: { description: 'Old.' } } },
    'PATCH /api/account/me': { body: { ok: true, user: { ...USER, name: 'Ada L.' } } },
  });
  const onUserChange = jest.fn();
  render(<AccountSignedIn user={USER} me={ME} apiKey="tok.1" isMobile={false} onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={onUserChange} />);
  expect(await screen.findByText('2 of 2')).toBeInTheDocument();
  expect(screen.getByText('3 of 5')).toBeInTheDocument();
  expect(screen.getByText('60')).toBeInTheDocument();
  expect(screen.getByText('Public profile →')).toHaveAttribute('href', '/agents/ada-lovelace');
  await waitFor(() => expect(screen.getByLabelText('About')).toHaveValue('Old.'));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada L.' } });
  fireEvent.change(screen.getByLabelText('About'), { target: { value: 'Reviews dosing.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByText('Saved.')).toBeInTheDocument();
  const name = calls.find((c) => c.url === '/api/account/me' && c.opts.method === 'PATCH');
  expect(JSON.parse(name.opts.body)).toEqual({ name: 'Ada L.' });
  expect(name.opts.headers.Authorization).toBe('Bearer tok.1');
  const about = calls.find((c) => c.url.includes('/v1/agents/ada-lovelace') && c.opts.method === 'PATCH');
  expect(JSON.parse(about.opts.body)).toEqual({ description: 'Reviews dosing.' });
  expect(onUserChange).toHaveBeenCalledWith({ ...USER, name: 'Ada L.' });
});

test('changing the password sends the current and new one and keeps the fresh token', async () => {
  localStorage.setItem('rrsrch_token', 'tok.1');
  const calls = mock({ '/api/account/password': { body: { ok: true, token: 'tok.2', user: USER } }, '/api/account/config': { body: {} } });
  render(<AccountSignedIn user={USER} me={null} apiKey="tok.1" isMobile={false} onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={jest.fn()} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Sign-in & security' }));
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
  fireEvent.change(screen.getByPlaceholderText('Current password'), { target: { value: 'old-one' } });
  fireEvent.change(screen.getByPlaceholderText('New password'), { target: { value: 'another-Horse-battery-9' } });
  fireEvent.click(screen.getAllByRole('button', { name: 'Change password' }).at(-1));
  expect(await screen.findByText('Password changed.')).toBeInTheDocument();
  expect(JSON.parse(calls.find((c) => c.url === '/api/account/password').opts.body))
    .toEqual({ current: 'old-one', next: 'another-Horse-battery-9' });
  expect(localStorage.getItem('rrsrch_token')).toBe('tok.2');
});

test('Google-only accounts have no password row; Disconnect forgets the agent key', async () => {
  localStorage.setItem('rrsrch_token', 'tok.1');
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  mock({ '/api/account/config': { body: {} } });
  const onKeyChange = jest.fn();
  render(<AccountSignedIn user={{ ...USER, google: true, has_password: false }} me={{ ...ME, handle: 'scout',
    organization_id: 'rrsrch', org_role: 'admin' }} apiKey="rrsrch_k" isMobile={false} onSignedOut={jest.fn()}
    onKeyChange={onKeyChange} onUserChange={jest.fn()} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Sign-in & security' }));
  expect(screen.queryByText('Email and password')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Connected' })).toBeDisabled();
  expect(screen.getByText('Acting as scout')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
  expect(localStorage.getItem('rrsrch_engine_key')).toBeNull();
  expect(onKeyChange).toHaveBeenCalledWith(null);
});

test('Account keeps account details, keys and search history; notifications are gone', async () => {
  mock({});
  render(<AccountSignedIn user={USER} me={null} apiKey="" isMobile={false} onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={jest.fn()} initialTab="keys" />);
  expect(screen.getAllByRole('tab').map((t) => t.textContent))
    .toEqual(['Profile', 'Organization', 'Sign-in & security', 'Keys', 'Search history']);
  expect(screen.getByRole('tab', { name: 'Keys' })).toHaveAttribute('aria-selected', 'true');   // #/account?tab=keys
  expect(await screen.findByText(/create an organization under the Organization tab/)).toBeInTheDocument();
  await settle();
});

test('an organization admin signed in on the site issues keys to its agents from Account › Keys', async () => {
  mock({
    '/v1/whoami': { body: { ok: true, handle: 'ominis-2', organization_id: 'ominis-labs', org_role: 'admin',
      scopes: ['read', 'propose', 'review', 'agents', 'administer'] } },
    '/v1/agents?organization=': { body: { ok: true, items: [
      { handle: 'ominis-2', status: 'active', kind: 'human' }, { handle: 'ominis', status: 'active', kind: 'model' },
      { handle: 'dae-chief-of-staff', status: 'active', kind: 'model' }, { handle: 'pat', status: 'active', kind: 'human' }] } },
    '/keys': { body: { ok: true, keys: [] } },
  });
  render(<AccountSignedIn user={USER} me={null} apiKey="" isMobile onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={jest.fn()} initialTab="keys" />);
  const agents = await screen.findByText("Your agents' keys (ominis-labs)");
  const own = screen.getByText('Your own key (ominis-2)');
  // the agents come first, so the first "Issue key" a person reaches is an agent's, not their own
  expect(agents.compareDocumentPosition(own) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText('ominis')).toBeInTheDocument();
  expect(screen.getByText('dae-chief-of-staff')).toBeInTheDocument();
  expect(screen.queryByText('pat')).not.toBeInTheDocument();                 // another person isn't an agent
  expect(screen.getByText(/can't propose\s+gauges or vote on them/)).toBeInTheDocument();
  expect(screen.queryByText(/Connect an agent's key under Sign-in/)).not.toBeInTheDocument();
  await settle();
});

test('an agent acting with its own key sees its keys first', async () => {
  mock({
    '/v1/whoami': { body: { ok: true, handle: 'ominis', organization_id: 'ominis-labs', org_role: 'member',
      scopes: ['read', 'propose', 'review'] } },
    '/v1/agents?organization=': { body: { ok: true, items: [
      { handle: 'ominis-2', status: 'active', kind: 'human' }, { handle: 'ominis', status: 'active', kind: 'model' }] } },
    '/keys': { body: { ok: true, keys: [] } },
  });
  render(<AccountSignedIn user={USER} me={null} apiKey="" isMobile onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={jest.fn()} initialTab="keys" />);
  expect(await screen.findByText('Issue a key for ominis')).toBeInTheDocument();
  expect(screen.queryByText(/Your own key/)).not.toBeInTheDocument();
  await settle();
});

test('an unverified account sees the confirm banner', () => {
  mock({});
  render(<AccountSignedIn user={{ ...USER, email_verified: false }} me={null} apiKey="" isMobile={false}
    onSignedOut={jest.fn()} onKeyChange={jest.fn()} onUserChange={jest.fn()} />);
  expect(screen.getByText(/to post, answer and comment/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Resend the link' })).toBeInTheDocument();
});

describe('organization tab', () => {
  const USER = { id: 'u1', name: 'Grace', email: 'g@x.test', email_verified: true, has_password: true };
  test('a confirmed account creates an organization with its sign-in, not an agent key', async () => {
    localStorage.setItem('rrsrch_token', 'site.tok');
    localStorage.setItem('rrsrch_engine_key', 'rrsrch_agentkey');
    let created = false;
    const calls = [];
    global.fetch = jest.fn(async (url, opts = {}) => {
      calls.push({ url, opts });
      if (url.includes('/v1/organizations') && opts.method === 'POST') { created = true; return { ok: true, status: 201, json: async () => ({ ok: true, organization: { id: 'hopper-lab' } }) }; }
      if (url.includes('/v1/whoami')) return { ok: true, status: 200, json: async () => (created ? { ok: true, handle: 'grace', organization_id: 'hopper-lab', org_role: 'admin', scopes: ['agents'] } : { ok: true, handle: 'grace', organization_id: 'people', org_role: 'member', scopes: ['read'] }) };
      if (url.includes('/v1/organizations/hopper-lab')) return { ok: true, status: 200, json: async () => ({ ok: true, organization: { id: 'hopper-lab', name: 'Hopper Lab', verification: 'unverified', agents: 1 } }) };
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    });
    render(<AccountSignedIn user={USER} apiKey="rrsrch_agentkey" me={null} isMobile={false} onSignedOut={() => {}}
      onKeyChange={() => {}} onUserChange={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Organization' }));
    fireEvent.change(await screen.findByPlaceholderText('my-lab'), { target: { value: 'Hopper-Lab' } });
    fireEvent.change(screen.getByPlaceholderText('My Lab'), { target: { value: 'Hopper Lab' } });
    fireEvent.click(screen.getByText('Create organization'));
    expect(await screen.findByText(/Unverified: your agents can work normally/)).toBeInTheDocument();
    const post = calls.find((c) => c.url.includes('/v1/organizations') && c.opts.method === 'POST');
    expect(post.opts.headers.Authorization).toBe('Bearer site.tok');
    expect(JSON.parse(post.opts.body)).toMatchObject({ id: 'hopper-lab', name: 'Hopper Lab' });
    localStorage.clear();
  });
  test('an unconfirmed account is asked to confirm first', () => {
    render(<AccountSignedIn user={{ ...USER, email_verified: false }} apiKey="" me={null} isMobile={false}
      onSignedOut={() => {}} onKeyChange={() => {}} onUserChange={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Organization' }));
    expect(screen.getByText(/Confirm your email first/)).toBeInTheDocument();
  });
});

test('an account whose password fails today\'s rules sets a new one before anything else', () => {
  const onSignedOut = jest.fn();
  render(<PasswordUpgrade user={{ ...USER, password_upgrade_required: true }} onDone={jest.fn()} onSignedOut={onSignedOut} />);
  expect(screen.getByText('Set a new password')).toBeInTheDocument();
  expect(screen.getByText(/has appeared in a data breach/)).toBeInTheDocument();
  expect(screen.getByText(/14 to 72 characters/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  expect(onSignedOut).toHaveBeenCalled();
});

test('a person picks a new handle: checked as typed, sent with their sign-in, and shown everywhere after', async () => {
  localStorage.setItem('rrsrch_token', 'tok.1');
  const change = { allowed: true, next_at: null, previous: [] };
  const calls = mock({
    'GET /v1/whoami': { body: { ok: true, ...ME, key_id: null, handle_change: change } },
    'POST /v1/me/handle': { body: { ok: true, handle: 'ada', changed: true, previous: ['ada-lovelace'],
      handle_change: { allowed: false, next_at: '2026-10-30T12:00:00Z', previous: ['ada-lovelace'] } } },
    '/v1/agents/': { body: { ok: true, agent: { description: '' } } },
  });
  const onMeChange = jest.fn();
  render(<AccountSignedIn user={USER} me={ME} apiKey="tok.1" isMobile={false} onSignedOut={jest.fn()}
    onKeyChange={jest.fn()} onUserChange={jest.fn()} onMeChange={onMeChange} />);
  const field = screen.getByRole('textbox', { name: 'Handle' });
  await waitFor(() => expect(field).toHaveValue('ada-lovelace'));
  fireEvent.change(field, { target: { value: 'a-' } });
  expect(screen.getByText('3 to 30 characters.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  fireEvent.change(field, { target: { value: '@Ada' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByText('Saved.')).toBeInTheDocument();
  const sent = calls.find((c) => c.url.endsWith('/v1/me/handle'));
  expect(JSON.parse(sent.opts.body)).toEqual({ handle: 'ada' });
  expect(sent.opts.headers.Authorization).toBe('Bearer tok.1');
  expect(onMeChange).toHaveBeenCalledWith({ ...ME, handle: 'ada' });
  expect(field).toBeDisabled();
  expect(screen.getByText(/You can change it again on Oct 30\./)).toBeInTheDocument();
  expect(screen.getByText(/Before: @ada-lovelace\./)).toBeInTheDocument();
});

test('the handle that changes is the one shown: a person\'s own key renames them, an agent\'s key can\'t', async () => {
  localStorage.setItem('rrsrch_token', 'tok.1');
  const calls = mock({
    'GET /v1/whoami': { body: { ok: true, ...ME, handle: 'demetri', organization_id: 'rrsrch', key_id: 9,
      handle_change: { allowed: true, next_at: null, previous: [] } } },
    'POST /v1/me/handle': { body: { ok: true, handle: 'dhodges', previous: ['demetri'],
      handle_change: { allowed: false, next_at: '2026-10-30T12:00:00Z', previous: ['demetri'] } } },
    '/v1/agents/': { body: { ok: true, agent: { description: '' } } },
  });
  const human = { ...ME, handle: 'demetri', organization_id: 'rrsrch', key_id: 9 };
  const onMeChange = jest.fn();
  const { unmount } = render(<AccountSignedIn user={USER} me={human} apiKey="tok.2" isMobile={false}
    onSignedOut={jest.fn()} onKeyChange={jest.fn()} onUserChange={jest.fn()} onMeChange={onMeChange} />);
  const field = screen.getByRole('textbox', { name: 'Handle' });
  await waitFor(() => expect(field).toHaveValue('demetri'));
  fireEvent.change(field, { target: { value: 'dhodges' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  expect(await screen.findByText('Saved.')).toBeInTheDocument();
  expect(calls.find((c) => c.url.endsWith('/v1/me/handle')).opts.headers.Authorization).toBe('Bearer tok.2');
  expect(onMeChange).toHaveBeenCalledWith({ ...human, handle: 'dhodges' });
  unmount();

  mock({ 'GET /v1/whoami': { body: { ok: true, ...ME, handle: 'milo', organization_id: 'rrsrch', key_id: 3,
    handle_change: null } }, '/v1/agents/': { body: { ok: true, agent: { description: '' } } } });
  render(<AccountSignedIn user={USER} me={{ ...ME, handle: 'milo' }} apiKey="tok.3" isMobile={false}
    onSignedOut={jest.fn()} onKeyChange={jest.fn()} onUserChange={jest.fn()} />);
  expect(await screen.findByText('An agent keeps the handle it signed up with.')).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Handle' })).toBeDisabled();
});
