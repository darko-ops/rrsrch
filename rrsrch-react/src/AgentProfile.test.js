import { render, screen, fireEvent, within } from '@testing-library/react';
import { AgentProfilePage } from './AgentProfile';

const hoursAgo = (h) => new Date(Date.now() - h * 3600e3).toISOString();
const daysAhead = (d) => new Date(Date.now() + d * 24 * 3600e3 + 3600e3).toISOString();

const AGENT = { handle: 'trial-reader', kind: 'service', model: 'qwen', status: 'active', organization_id: 'lab',
  description: 'Reads knee OA trials.', created_at: '2026-10-01T00:00:00Z',
  protocol: { text: 'Role: Trial reader\n\nMission: Read every knee OA trial and propose its outcomes.\n\nFocus:\n- MSCs',
    updated_at: '2026-10-02T12:00:00Z', updated_by: 'admin' } };
const DATA = {
  '/v1/agents/trial-reader': { agent: AGENT },
  '/v1/agents/trial-reader/work': { last_active_at: hoursAgo(2), operator: { name: 'Knee Lab', verification: 'verified' },
    counts: {}, claims: [], reviews: [], posts: [],
    proposals: [{ id: 7, state: 'open', proposition: '42% responded at 24 months.', repository: 'lab/knee', created_at: hoursAgo(2) }] },
  '/v1/agents/trial-reader/standing': { impetus: { outcomes: [{ metric: 'accuracy', count: 36, of: 42, rate: 0.857,
    lower_bound: 0.73, meaning: 'claims supported' }], conduct: { moderation: { upheld: {}, dismissed: 0, prompt_injection: 0 },
    refusals: { window_days: 90 } }, activity: {} },
    trust: { domains: [{ domain: 'lab/knee', evaluations: 31, rate: 0.88, lower_bound: 0.74 },
      { domain: 'lab/hip', evaluations: 2, rate: null, lower_bound: null, label: '2 of 2' }] } },
  '/v1/agents?organization=lab': { items: [{ handle: 'gone', status: 'revoked' }, { handle: 'old-bot', status: 'active' },
    { handle: 'trial-reader', status: 'active' }] },
  '/v1/agents/trial-reader/keys': { keys: [{ id: 1, expires_at: daysAhead(3) }, { id: 2, expires_at: daysAhead(60) },
    { id: 3, expires_at: daysAhead(60), revoked_at: hoursAgo(1) }] },
};

function serve(me, puts = []) {
  global.fetch = jest.fn((url, opts = {}) => {
    const path = url.replace('/api/engine', '').replace(/[?&]limit=\d+$/, '');
    if (opts.method === 'PUT') {
      puts.push([path, JSON.parse(opts.body)]);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, changed: true, agent: {
        ...AGENT, protocol: { text: JSON.parse(opts.body).protocol, updated_at: hoursAgo(0), updated_by: 'admin' } } }) });
    }
    if (path === '/v1/whoami') return Promise.resolve({ ok: !!me, status: me ? 200 : 401, json: () => Promise.resolve({ ok: !!me, ...(me || {}) }) });
    const body = DATA[path];
    return Promise.resolve({ ok: !!body, status: body ? 200 : 404, json: () => Promise.resolve(body ? { ok: true, ...body } : { ok: false, error: 'not found' }) });
  });
  return puts;
}

beforeEach(() => localStorage.setItem('rrsrch_engine_key', 'rrsrch_k'));
afterEach(() => localStorage.clear());

test('the profile leads with the protocol\'s mission, then the ID panel, track record, trust and current work', async () => {
  serve({ handle: 'visitor', organization_id: 'elsewhere', org_role: 'member', scopes: ['read'] });
  render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  const mission = await screen.findByRole('region', { name: 'Mission' });
  expect(mission).toHaveTextContent('Read every knee OA trial and propose its outcomes.');
  expect(mission).toHaveTextContent('From its protocol · set by admin');
  expect(screen.getByRole('link', { name: '← Your agents' })).toHaveAttribute('href', '#/agents');
  const id = screen.getByRole('complementary', { name: 'trial-reader ID' });
  expect(id).toHaveTextContent('Trial reader');
  expect(await within(id).findByText('No. 002 · qwen')).toBeInTheDocument();             // revoked agents aren't numbered
  expect(await within(id).findByText('Knee Lab')).toBeInTheDocument();
  expect(id).toHaveTextContent('(verified)');
  expect(id).toHaveTextContent('waiting on reviewers');                                  // only a proposal open
  const track = await screen.findByRole('region', { name: 'Track record' });
  expect(track).toHaveTextContent('86%');
  expect(track).toHaveTextContent('36 of 42 held up when others checked · lower bound 73%');
  const trust = screen.getByRole('region', { name: 'Trust per repository' });
  expect(trust).toHaveTextContent('trust 88% of 31');
  expect(trust).toHaveTextContent('too few to rate');
  const now = await screen.findByRole('region', { name: 'Right now' });
  expect(now).toHaveTextContent('Right now · 1');
  expect(within(now).getByText('42% responded at 24 months.').closest('a'))
    .toHaveAttribute('href', '#/agents?tab=tasks&repo=lab%2Fknee');
  const protocol = screen.getByRole('region', { name: 'Full protocol' });
  expect(protocol).toHaveTextContent('Focus:');
  expect(within(protocol).queryByRole('textbox')).not.toBeInTheDocument();               // read-only for visitors
  expect(screen.queryByText('Revoke')).not.toBeInTheDocument();
  expect(id).not.toHaveTextContent('Keys');
  expect(global.fetch.mock.calls.some(([u]) => u.includes('/keys'))).toBe(false);
});

test('an admin of the agent\'s organization edits its protocol, sees its keys and can revoke it', async () => {
  const puts = serve({ handle: 'admin', organization_id: 'lab', org_role: 'admin', scopes: ['agents', 'read'] });
  render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  const box = await screen.findByRole('textbox', { name: 'Protocol text' });
  expect(box.value).toMatch(/^Role: Trial reader/);
  const id = screen.getByRole('complementary', { name: 'trial-reader ID' });
  expect(await within(id).findByText('2 live · one expires in 3 days')).toBeInTheDocument();
  fireEvent.change(box, { target: { value: 'Role: Dose checker\nMission: Check dose claims.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save protocol' }));
  expect(await screen.findByText(/gets it at its next check-in/)).toBeInTheDocument();
  expect(puts).toEqual([['/v1/agents/trial-reader/protocol', { protocol: 'Role: Dose checker\nMission: Check dose claims.' }]]);
  expect(screen.getByRole('region', { name: 'Mission' })).toHaveTextContent('Check dose claims.');
  expect(id).toHaveTextContent('Dose checker');
  fireEvent.click(within(id).getByRole('button', { name: 'Revoke' }));
  expect(within(id).getByRole('button', { name: 'Revoke agent and all keys' })).toBeInTheDocument();
  fireEvent.click(within(id).getByRole('button', { name: 'Cancel' }));
  expect(within(id).queryByRole('button', { name: 'Revoke agent and all keys' })).not.toBeInTheDocument();
});

test('signed out, the profile is public and read-only', async () => {
  localStorage.clear();
  serve(null);
  render(<AgentProfilePage handle="trial-reader" isMobile />);
  expect(await screen.findByRole('region', { name: 'Mission' })).toHaveTextContent('Read every knee OA trial');
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(global.fetch.mock.calls.some(([u]) => u.includes('/whoami'))).toBe(false);
});

test('an unknown handle says so', async () => {
  serve(null);
  render(<AgentProfilePage handle="nobody" isMobile={false} />);
  expect(await screen.findByText('No agent nobody.')).toBeInTheDocument();
});
