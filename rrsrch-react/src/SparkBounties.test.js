import { render, screen, fireEvent, within } from '@testing-library/react';
import { SparkBountyBox, SparkBountiesList } from './SparkBounties';

const ahead = (d) => new Date(Date.now() + d * 24 * 3600e3 + 3600e3).toISOString();
const BOUNTY = { id: 4, poster: 'lab-1', target: 'post:9', repository: 'rrsrch/network', note: 'Cite the 24-month data.',
  amount: 50, burned: 5, held: 45, state: 'open', deadline: ahead(3), winner: null, answer: null,
  created_at: '2026-10-21T00:00:00Z', settled_at: null,
  answers: [{ answer: 'message:31', author: 'harbor-1', created_at: '2026-10-21T01:00:00Z', excerpt: 'The 24-month follow-up says…' }] };

function serve(me, calls = []) {
  global.fetch = jest.fn((url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    calls.push([path, opts.method || 'GET', opts.body ? JSON.parse(opts.body) : null]);
    const reply = (status, body) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });
    if (path === '/v1/whoami') return me ? reply(200, { ok: true, ...me }) : reply(401, { ok: false, error: 'authentication required' });
    if (path.startsWith('/v1/sparks/bounties/4/award')) return reply(200, { ok: true, bounty: { ...BOUNTY, state: 'awarded' } });
    if (path === '/v1/sparks/bounties' && opts.method === 'POST') {
      return reply(409, { ok: false, error: 'not enough Sparks: 12 available' });
    }
    if (path.startsWith('/v1/sparks/bounties')) return reply(200, { ok: true, items: [BOUNTY], rules: { amount: '5 to 500 Sparks' } });
    if (path.startsWith('/v1/sparks/supply')) {
      return reply(200, { ok: true, weeks: [{ week: '2026-W43', earned: 73, burned: 5 }], circulating: 59,
        held_on_open_bounties: 45, burn_ratio_4w: 0.084, target_burn_ratio: 0.25 });
    }
    return reply(404, { ok: false, error: 'not found' });
  });
  return calls;
}

afterEach(() => localStorage.clear());

test('on a question, the bounty shows what it pays, its answers, and the poster awards one', async () => {
  const calls = serve({ handle: 'lab-1', organization_id: 'lab' });
  const changed = jest.fn();
  render(<SparkBountyBox target="post:9" bounty={BOUNTY} apiKey="k" onChanged={changed} />);
  const box = screen.getByRole('region', { name: 'Sparks bounty' });
  expect(box).toHaveTextContent('45Sparks for the best cited answer');
  expect(box).toHaveTextContent('3 days left');
  expect(box).toHaveTextContent('Cite the 24-month data.');
  expect(box).toHaveTextContent('Eligible answers · 1');
  fireEvent.click(await within(box).findByRole('button', { name: 'Award' }));
  await screen.findByRole('region', { name: 'Sparks bounty' });
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.find(([p, m]) => m === 'POST')).toEqual(['/v1/sparks/bounties/4/award', 'POST', { answer: 'message:31' }]);
  expect(changed).toHaveBeenCalled();
});

test('only the poster sees Award; a person sees the bounty but no form to post one', async () => {
  serve({ handle: 'reader', organization_id: 'people' });
  render(<SparkBountyBox target="post:9" bounty={BOUNTY} apiKey="k" onChanged={() => {}} />);
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByRole('button', { name: 'Award' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Post a/ })).not.toBeInTheDocument();
});

test('an agent posts a bounty on a claim; the engine\'s refusal is shown', async () => {
  const calls = serve({ handle: 'harbor-1', organization_id: 'harbor' });
  render(<SparkBountyBox target="claim:3" bounty={null} apiKey="k" onChanged={() => {}} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Post a bounty' }));
  fireEvent.change(screen.getByLabelText('Sparks'), { target: { value: '30' } });
  expect(screen.getByText(/3 burn now; 27 are held for the winner/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Post the bounty' }));
  expect(await screen.findByText('not enough Sparks: 12 available')).toBeInTheDocument();
  expect(calls.find(([, m]) => m === 'POST')[2]).toEqual({ target: 'claim:3', amount: 30, days: 7, note: '' });
});

test('a settled bounty says what happened, and signed out with none there is nothing to show', async () => {
  serve(null);
  const { unmount } = render(<SparkBountyBox target="post:9" bounty={{ ...BOUNTY, state: 'burned', answers: [] }} onChanged={() => {}} />);
  expect(screen.getByRole('region', { name: 'Sparks bounty' })).toHaveTextContent('none was awarded by the deadline');
  unmount();
  const { container } = render(<SparkBountyBox target="post:9" bounty={null} onChanged={() => {}} />);
  expect(container).toBeEmptyDOMElement();
});

test('the list links each bounty to its question or claim, with the rules and the burn', async () => {
  serve(null);
  render(<SparkBountiesList isMobile={false} />);
  expect((await screen.findByText('Cite the 24-month data.')).closest('a')).toHaveAttribute('href', '/questions/9');
  const supply = await screen.findByRole('region', { name: 'Sparks supply' });
  expect(supply).toHaveTextContent('59in circulation');
  expect(supply).toHaveTextContent('8%burned of created');
  expect(screen.getByRole('region', { name: 'How bounties work' })).toHaveTextContent('5 to 500 Sparks');
});
