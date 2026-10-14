import { render, screen, fireEvent } from '@testing-library/react';
import MembersPanel from './Members';

function mock(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const hit = Object.keys(routes).find((k) => url.includes(k) && (!routes[k].method || routes[k].method === (opts.method || 'GET')));
    const r = hit ? routes[hit] : { status: 200, body: { ok: true } };
    return { ok: (r.status || 200) < 400, status: r.status || 200, json: async () => r.body };
  });
  return calls;
}
const REPOS = [{ slug: 'rrsrch/msc-knee-oa' }];

test('owners see members, grant a role and remove one', async () => {
  const calls = mock({
    '/members/scout': { method: 'PUT', body: { ok: true } },
    '/members/bot': { method: 'DELETE', body: { ok: true, removed: true } },
    '/v1/repos/rrsrch/msc-knee-oa/members': { body: { ok: true, members: [
      { handle: 'bot', role: 'contributor', organization_id: 'rrsrch', granted_by: null }] } },
  });
  render(<MembersPanel apiKey="k" repos={REPOS} repo="rrsrch/msc-knee-oa" onRepo={() => {}} />);
  expect(await screen.findByText('bot')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('agent handle'), { target: { value: 'Scout' } });
  fireEvent.change(screen.getByLabelText('role'), { target: { value: 'reviewer' } });
  fireEvent.click(screen.getByText('Grant role'));
  expect(await screen.findByText('scout is now reviewer of rrsrch/msc-knee-oa.')).toBeInTheDocument();
  expect(JSON.parse(calls.find((c) => c.opts.method === 'PUT').opts.body)).toEqual({ role: 'reviewer' });
  fireEvent.click(screen.getByText('Remove'));
  expect(await screen.findByText('bot no longer has a role in rrsrch/msc-knee-oa.')).toBeInTheDocument();
});

test('non-maintainers are told who can manage members', async () => {
  mock({ '/members': { status: 403, body: { ok: false, error: 'contributor cannot maintain (needs maintainer)' } } });
  render(<MembersPanel apiKey="k" repos={REPOS} repo="rrsrch/msc-knee-oa" onRepo={() => {}} />);
  expect(await screen.findByText(/Only maintainers and owners/)).toBeInTheDocument();
});
