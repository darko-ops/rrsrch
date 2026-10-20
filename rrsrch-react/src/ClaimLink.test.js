import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ClaimLink, { orgIdOf, PENDING_CLAIM } from './ClaimLink';

const AGENT = { handle: 'scout', kind: 'model', model: 'acme/m1', description: 'Reads trial registries',
  signed_up_at: '2026-10-20T10:00:00Z', claim_expires_at: '2026-11-19T10:00:00Z' };

function serve(whoami, calls = []) {
  global.fetch = jest.fn((url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    calls.push([opts.method || 'GET', path, opts.body ? JSON.parse(opts.body) : null]);
    const ok = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, ...d }) });
    if (path === '/v1/agents/claim/preview') return ok({ agent: AGENT });
    if (path === '/v1/whoami') return ok(whoami());
    if (path === '/v1/organizations') return ok({ organization: { id: 'harbor-lab' } });
    if (path === '/v1/agents/claim') return ok({ handle: 'scout', organization_id: 'harbor-lab' });
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ ok: false, error: 'not found' }) });
  });
  return calls;
}

afterEach(() => localStorage.clear());

test('an organization id comes from its name', () => {
  expect(orgIdOf('Harbor Lab!')).toBe('harbor-lab');
  expect(orgIdOf('  Über  Research  ')).toBe('uber-research');
});

test('signed out, the link shows the agent and a sign-in, and remembers the code', async () => {
  serve(() => ({}));
  render(<ClaimLink code="claim_abcdefghijkl" user={null} isMobile={false} onSignedIn={() => {}} />);
  expect(await screen.findByText('Reads trial registries')).toBeInTheDocument();
  expect(screen.getByText(/Sign in or create an account to claim it/)).toBeInTheDocument();
  expect(localStorage.getItem(PENDING_CLAIM)).toBe('claim_abcdefghijkl');
});

test('a person with no organization names one and claims the agent in one step', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  let org = 'people';
  const calls = serve(() => ({ handle: 'dana', organization_id: org, org_role: org === 'people' ? 'member' : 'admin' }));
  render(<ClaimLink code="claim_abcdefghijkl" user={{ email: 'x@example.org', email_verified: true }} isMobile={false} />);
  fireEvent.change(await screen.findByLabelText('organization name'), { target: { value: 'Harbor Lab' } });
  expect(screen.getByLabelText('organization id')).toHaveValue('harbor-lab');
  org = 'harbor-lab';
  fireEvent.click(screen.getByRole('button', { name: 'Create it and claim scout' }));
  expect(await screen.findByText(/is now in/)).toBeInTheDocument();
  const writes = calls.filter(([m]) => m === 'POST').map(([, p, b]) => [p, b]);
  expect(writes).toEqual([
    ['/v1/agents/claim/preview', { code: 'claim_abcdefghijkl' }],
    ['/v1/organizations', { id: 'harbor-lab', name: 'Harbor Lab' }],
    ['/v1/agents/claim', { code: 'claim_abcdefghijkl' }],
  ]);
  await waitFor(() => expect(localStorage.getItem(PENDING_CLAIM)).toBeFalsy());
});

test('an organization admin claims with one click', async () => {
  localStorage.setItem('rrsrch_token', 'site_tok');
  serve(() => ({ handle: 'dana', organization_id: 'harbor-lab', org_role: 'admin' }));
  render(<ClaimLink code="claim_abcdefghijkl" user={{ email: 'x@example.org', email_verified: true }} isMobile={false} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Claim scout' }));
  expect(await screen.findByRole('link', { name: 'Give it orders' })).toHaveAttribute('href', '/agents/scout?tab=protocol');
});
