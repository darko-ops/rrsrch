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
afterEach(() => { localStorage.clear(); window.history.replaceState(null, '', '/'); });

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
  const trust = screen.getByRole('region', { name: 'Trust per collection' });
  expect(trust).toHaveTextContent('trust 88% of 31');
  expect(trust).toHaveTextContent('too few to rate');
  const now = await screen.findByRole('region', { name: 'Right now' });
  expect(now).toHaveTextContent('Right now · 1');
  expect(within(now).getByText('42% responded at 24 months.').closest('a'))
    .toHaveAttribute('href', '#/agents?tab=tasks&repo=lab%2Fknee');
  expect(screen.getByText('Everything it added')).toBeInTheDocument();                  // the overview has its posts
  expect(screen.queryByRole('region', { name: 'Orders' })).not.toBeInTheDocument();
  expect(screen.queryByText('Full standing')).not.toBeInTheDocument();
  // the protocol tab: its orders, read-only for visitors, and in the address
  fireEvent.click(screen.getByRole('tab', { name: 'Protocol' }));
  expect(window.location.search).toBe('?tab=protocol');
  const orders = screen.getByRole('region', { name: 'Orders' });
  expect(orders).toHaveTextContent('Focus:');
  expect(within(orders).queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Mission' })).not.toBeInTheDocument();
  expect(screen.getByRole('complementary', { name: 'trial-reader ID' })).toBeInTheDocument();  // the ID panel stays
  // more info: its full standing
  fireEvent.click(screen.getByRole('tab', { name: 'More info' }));
  expect(screen.getByText('Full standing')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Orders' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Overview' }));
  expect(window.location.search).toBe('');
  expect(screen.queryByText('Revoke')).not.toBeInTheDocument();
  expect(id).not.toHaveTextContent('Keys');
  expect(global.fetch.mock.calls.some(([u]) => u.includes('/keys'))).toBe(false);
});

test('an admin of the agent\'s organization gives it orders, sees its keys and can revoke it', async () => {
  const puts = serve({ handle: 'admin', organization_id: 'lab', org_role: 'admin', scopes: ['agents', 'read'] });
  render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  fireEvent.click(await screen.findByRole('tab', { name: 'Protocol' }));
  const orders = screen.getByRole('region', { name: 'Orders' });                         // a form filled from the protocol
  expect(within(orders).getByRole('textbox', { name: 'Role' })).toHaveValue('Trial reader');
  expect(within(orders).getByRole('textbox', { name: 'Focus' })).toHaveValue('MSCs');
  const id = screen.getByRole('complementary', { name: 'trial-reader ID' });
  expect(await within(id).findByText('2 live · one expires in 3 days')).toBeInTheDocument();
  fireEvent.change(within(orders).getByRole('textbox', { name: 'Role' }), { target: { value: 'Dose checker' } });
  fireEvent.change(within(orders).getByRole('textbox', { name: 'Mission' }), { target: { value: 'Check dose claims.' } });
  fireEvent.change(within(orders).getByRole('textbox', { name: 'Avoid' }), { target: { value: '- animal studies\npreprints' } });
  // the same orders as text, and back
  fireEvent.click(within(orders).getByRole('button', { name: 'Edit as text' }));
  const text = 'Role: Dose checker\n\nMission: Check dose claims.\n\nFocus:\n- MSCs\n\nAvoid:\n- animal studies\n- preprints';
  expect(within(orders).getByRole('textbox', { name: 'Protocol text' })).toHaveValue(text);
  fireEvent.click(within(orders).getByRole('button', { name: 'Edit as a form' }));
  fireEvent.click(within(orders).getByRole('button', { name: 'Save orders' }));
  expect(await screen.findByText('Saved. trial-reader gets these orders at its next check-in.')).toBeInTheDocument();
  expect(puts).toEqual([['/v1/agents/trial-reader/protocol', { protocol: text }]]);
  fireEvent.click(screen.getByRole('tab', { name: 'Overview' }));
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

test('an admin of an agent with no orders is sent to its protocol tab, and a ?tab= link opens on it', async () => {
  serve({ handle: 'admin', organization_id: 'lab', org_role: 'admin', scopes: ['agents', 'read'] });
  DATA['/v1/agents/bare'] = { agent: { ...AGENT, handle: 'bare', protocol: null } };
  render(<AgentProfilePage handle="bare" isMobile={false} />);
  const mission = await screen.findByRole('region', { name: 'Mission' });
  expect(mission).toHaveTextContent('No orders yet.');
  expect(await screen.findByRole('tab', { name: 'Protocol none yet' })).toBeInTheDocument();
  fireEvent.click(within(mission).getByRole('button', { name: 'Give it orders' }));
  expect(screen.getByRole('tab', { name: 'Protocol none yet' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('region', { name: 'Orders' })).toHaveTextContent('Orders · none yet');
  delete DATA['/v1/agents/bare'];
});

test('a link to ?tab=more opens on its full standing', async () => {
  serve(null);
  window.history.replaceState(null, '', '/agents/trial-reader?tab=more');
  render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  expect(await screen.findByText('Full standing')).toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'More info' })).toHaveAttribute('aria-selected', 'true');
});
