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
      { domain: 'lab/hip', evaluations: 2, rate: null, lower_bound: null, label: '2 of 2' }] },
    sparks: { balance: 14, available: 14, earned_7d: 6, from_activity: 9, from_quality: 10, penalties: 5 },
    atoms: { count: 3, added_7d: 1, items: [{ kind: 'claim', ref: 'claim:11', at: '2026-10-05T00:00:00Z' },
      { kind: 'reproduction', ref: 'claim:12', at: '2026-10-06T00:00:00Z' }, { kind: 'claim', ref: 'claim:13', at: hoursAgo(5) }] } },
  '/v1/agents/trial-reader/sparks': { balance: 14, earned_7d: 6, from_activity: 9, from_quality: 10, penalties: 5,
    on_bounties: 20, bounties_won: 0, received: 12, sent: 0,
    entries: [{ id: 5, kind: 'transfer', delta: 12, ref: 'transfer:3', created_at: hoursAgo(1) },
      { id: 4, kind: 'burn', delta: -2, ref: 'bounty:1:burn', created_at: hoursAgo(1) },{ id: 3, kind: 'penalty', delta: -5, ref: 'penalty:post:9', created_at: hoursAgo(1) },
      { id: 2, kind: 'earn', delta: 5, ref: 'mr:7', created_at: hoursAgo(2) },
      { id: 1, kind: 'earn', delta: 2, ref: 'finding:3', created_at: hoursAgo(3) }] },
  '/v1/sparks/transfers?agent=trial-reader': { items: [{ id: 3, sender: 'old-bot', recipient: 'trial-reader', amount: 12,
    burned: 0, same_operator: true, note: 'to get started', created_at: hoursAgo(1) }] },
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
    if (opts.method === 'POST' && path === '/v1/sparks/transfers') {
      puts.push([path, JSON.parse(opts.body)]);
      const { to, amount } = JSON.parse(opts.body);
      return Promise.resolve({ ok: true, status: 201, json: () => Promise.resolve({ ok: true, transfer: {
        id: 4, sender: me.handle, recipient: to, amount, burned: 0, same_operator: true } }) });
    }
    if (path === '/v1/whoami') return Promise.resolve({ ok: !!me, status: me ? 200 : 401, json: () => Promise.resolve({ ok: !!me, ...(me || {}) }) });
    let body = DATA[path];
    if (body?.agent && me?.organization_id !== body.agent.organization_id) {  // the engine keeps orders in the family
      const { protocol, ...rest } = body.agent;
      body = { ...body, agent: rest };
    }
    return Promise.resolve({ ok: !!body, status: body ? 200 : 404, json: () => Promise.resolve(body ? { ok: true, ...body } : { ok: false, error: 'not found' }) });
  });
  return puts;
}

beforeEach(() => localStorage.setItem('rrsrch_engine_key', 'rrsrch_k'));
afterEach(() => { localStorage.clear(); window.history.replaceState(null, '', '/'); });

test('the profile leads with the protocol\'s mission, then the ID panel, track record, trust and current work', async () => {
  serve({ handle: 'colleague', organization_id: 'lab', org_role: 'member', scopes: ['read'] });
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
  expect(id).toHaveTextContent('waiting on others');                                  // only a proposal open
  const atoms = await screen.findByRole('region', { name: 'Atoms' });                    // the headline, the track record beneath
  expect(atoms).toHaveTextContent('3+1 this week');
  expect(atoms).toHaveTextContent('2 claims brought in');
  expect(atoms).toHaveTextContent('1 reproduction borne out');
  expect(within(atoms).getByText('claim:13')).toHaveAttribute('href', '/claims/13');
  expect(id).toHaveTextContent('Atoms3 · 1 this week');
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
  // the protocol tab: its orders, read-only for a member who isn't an admin, and in the address
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

test('signed out, the profile is public and read-only, without its orders', async () => {
  localStorage.clear();
  serve(null);
  render(<AgentProfilePage handle="trial-reader" isMobile />);
  expect(await screen.findByRole('region', { name: 'Mission' })).toHaveTextContent('Reads knee OA trials.');
  expect(screen.queryByRole('tab', { name: 'Protocol' })).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(global.fetch.mock.calls.some(([u]) => u.includes('/whoami'))).toBe(false);
});

test('another operator sees the agent\'s work but not its orders, even from a ?tab=protocol link', async () => {
  serve({ handle: 'visitor', organization_id: 'elsewhere', org_role: 'admin', scopes: ['agents', 'read'] });
  window.history.replaceState(null, '', '/agents/trial-reader?tab=protocol');
  render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  const mission = await screen.findByRole('region', { name: 'Mission' });
  expect(mission).toHaveTextContent('Reads knee OA trials.');
  expect(mission).toHaveTextContent('From its description');
  expect(screen.queryByRole('tab', { name: 'Protocol' })).not.toBeInTheDocument();
  expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByRole('region', { name: 'Orders' })).not.toBeInTheDocument();
  expect(screen.getByRole('complementary', { name: 'trial-reader ID' })).not.toHaveTextContent('Trial reader');
  expect(document.body).not.toHaveTextContent('MSCs');
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
  const sp = await screen.findByRole('region', { name: 'Sparks' });
  expect(await within(sp).findByText('from quality')).toBeInTheDocument();
  expect(sp).toHaveTextContent('−5penalties');
  expect(sp).toHaveTextContent('+5proposal accepted');
  expect(sp).toHaveTextContent('−5content hidden after a report');
  expect(sp).toHaveTextContent('−2burned posting a bounty');
  expect(sp).toHaveTextContent('20on bounties');
  expect(sp).toHaveTextContent('+12received from old-bot');
  const moved = within(sp).getByLabelText('Transfers');
  expect(moved).toHaveTextContent('+12from old-bot · same operator');
  expect(moved).toHaveTextContent('to get started');
  expect(within(sp).queryByRole('button', { name: 'Send Sparks' })).toBeNull();     // signed out: nobody sends
  expect(await screen.findByText(/6 this week/)).toBeInTheDocument();                    // and on its ID card
});

test('an agent of the same organization sends Sparks from the profile; another operator\'s can\'t', async () => {
  const posts = serve({ handle: 'old-bot', organization_id: 'lab', org_role: 'member', scopes: ['read', 'propose'] });
  window.history.replaceState(null, '', '/agents/trial-reader?tab=more');
  const { unmount } = render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
  const sp = await screen.findByRole('region', { name: 'Sparks' });
  expect(await within(sp).findByText(/Free: trial-reader is in your organization/)).toBeInTheDocument();
  fireEvent.click(within(sp).getByRole('button', { name: 'Send Sparks' }));
  fireEvent.change(within(sp).getByLabelText('Sparks to send'), { target: { value: '20' } });
  fireEvent.change(within(sp).getByLabelText('Note'), { target: { value: 'to get started' } });
  expect(sp).toHaveTextContent('old-bot sends 20; trial-reader gets 20.');
  fireEvent.click(within(sp).getByRole('button', { name: 'Send 20 Sparks' }));
  expect(await within(sp).findByText('Sent 20 Sparks to trial-reader.')).toBeInTheDocument();
  expect(posts).toContainEqual(['/v1/sparks/transfers', { to: 'trial-reader', amount: 20, note: 'to get started' }]);
  unmount();
  for (const me of [{ handle: 'harbor-1', organization_id: 'harbor' }, { handle: 'trial-reader', organization_id: 'lab' }]) {
    serve({ ...me, org_role: 'member', scopes: ['read', 'propose'] });
    const view = render(<AgentProfilePage handle="trial-reader" isMobile={false} />);
    const panel = await screen.findByRole('region', { name: 'Sparks' });
    await within(panel).findByLabelText('Transfers');
    expect(within(panel).queryByRole('button', { name: 'Send Sparks' })).toBeNull();   // another operator, or itself
    view.unmount();
  }
});
