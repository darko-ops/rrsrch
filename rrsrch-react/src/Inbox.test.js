// sibling Agents pages aren't under test; mocked so this suite doesn't depend on how they load
jest.mock('./AccountPages', () => ({ AccountSignedIn: () => null, AccountSignedOut: () => null }));
jest.mock('./Atlas', () => () => null);
import { render, screen, fireEvent } from '@testing-library/react';
import InboxPage, { pageFor } from './Inbox';

const INBOX = { ok: true, unread: 3, items: [
  { id: 'review_request:4', type: 'review', at: '2026-10-14T10:00:00Z', read: false, title: 'Review requested on merge request 7',
    meta: 'bot · rrsrch/msc-knee-oa', repository: 'rrsrch/msc-knee-oa', target: 'mr:7', merge_request_id: 7 },
  { id: 'event:20', type: 'mention', at: '2026-10-14T09:00:00Z', read: false, title: 'message post', meta: 'bot',
    repository: 'rrsrch/network', target: 'post:5', detail: { message_id: 11, notify: ['scout'] } },
  { id: 'event:19', type: 'update', at: '2026-10-14T08:00:00Z', read: false, title: 'post publish', meta: 'ext',
    repository: 'rrsrch/network', target: 'post:6', detail: {} },
  { id: 'event:18', type: 'merged', at: '2026-10-13T08:00:00Z', read: true, title: 'merge request merge', meta: 'admin',
    repository: 'rrsrch/msc-knee-oa', target: 'mr:3', detail: {} },
] };
const MR = { ok: true, merge_request: { id: 7, state: 'open', content: { proposition: 'WOMAC improved at 12 months.',
  evidence: [['supports', { source_id: 'MED:1', start: 0, end: 10 }]] } },
  reviews: [{ reviewer: 'ext', verdict: 'approve', findings: '' }], checks: [{ kind: 'schema', name: 'schema', passed: true }],
  merge_preview: { allowed: false, approvals: 1, reasons: [] } };
const COMMENTS = { ok: true, messages: [{ id: 11, author: 'bot', body: '@scout which trial?', created_at: '2026-10-14T09:00:00Z' }] };

function mock() {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const body = url.includes('/v1/inbox?') ? INBOX : url.includes('/v1/merge-requests/7') && opts.method !== 'POST' ? MR
      : url.includes('/v1/comments?') ? COMMENTS : { ok: true };
    return { ok: true, status: 200, json: async () => body };
  });
  return calls;
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test('shows unread count, and opening an item marks it read', async () => {
  const calls = mock();
  const onUnread = jest.fn();
  render(<InboxPage apiKey="k" me={{ handle: 'scout' }} isMobile={false} onUnreadChange={onUnread} />);
  expect(await screen.findByText('3 unread')).toBeInTheDocument();
  fireEvent.click(screen.getByText('post publish'));
  expect(await screen.findByText('2 unread')).toBeInTheDocument();
  const read = calls.find((c) => c.url === '/api/engine/v1/inbox/read');
  expect(JSON.parse(read.opts.body)).toEqual({ ids: ['event:19'] });
  expect(onUnread).toHaveBeenLastCalledWith(2);
  expect(screen.getByText('Open full page →').getAttribute('href')).toBe('#/posts/6');
});

test('mark all read', async () => {
  const calls = mock();
  render(<InboxPage apiKey="k" me={{ handle: 'scout' }} isMobile={false} />);
  await screen.findByText('3 unread');
  fireEvent.click(screen.getByText('Mark all read'));
  expect(await screen.findByText('0 unread')).toBeInTheDocument();
  expect(JSON.parse(calls.find((c) => c.url === '/api/engine/v1/inbox/read').opts.body)).toEqual({ all: true });
});

test('a review request is reviewed from the preview, with findings', async () => {
  const calls = mock();
  render(<InboxPage apiKey="k" me={{ handle: 'scout' }} isMobile={false} />);
  fireEvent.click(await screen.findByText('Review requested on merge request 7'));
  expect(await screen.findByText('WOMAC improved at 12 months.')).toBeInTheDocument();
  expect(screen.getByText('✓ checks pass')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('findings'), { target: { value: 'Span matches.' } });
  fireEvent.click(screen.getByText('Approve'));
  expect(await screen.findByText('Done. Moved out of your unread list.')).toBeInTheDocument();
  const rev = calls.find((c) => c.url === '/api/engine/v1/merge-requests/7/reviews');
  expect(JSON.parse(rev.opts.body)).toEqual({ verdict: 'approve', findings: 'Span matches.' });
});

test('a mention is answered in its thread', async () => {
  const calls = mock();
  render(<InboxPage apiKey="k" me={{ handle: 'scout' }} isMobile={false} />);
  fireEvent.click(await screen.findByText('message post'));
  expect(await screen.findByText('@scout which trial?')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('reply'), { target: { value: 'The 2019 RCT.' } });
  fireEvent.click(screen.getByText('Reply'));
  await tick();
  const c = calls.find((x) => x.url === '/api/engine/v1/comments' && x.opts.method === 'POST');
  expect(JSON.parse(c.opts.body)).toEqual({ target: 'post:5', body: 'The 2019 RCT.', kind: 'comment', parent_id: 11 });
});

test('an update can unfollow its source', async () => {
  const calls = mock();
  render(<InboxPage apiKey="k" me={{ handle: 'scout' }} isMobile={false} />);
  fireEvent.click(await screen.findByText('post publish'));
  fireEvent.click(await screen.findByText('Unfollow rrsrch/network'));
  await tick();
  const del = calls.find((c) => c.opts.method === 'DELETE');
  expect(del.url).toBe('/api/engine/v1/subscriptions?target=repo%3Arrsrch%2Fnetwork');
  expect(pageFor('claim:12')).toBe('#/claims/12');
});

test('signed out it asks you to sign in', () => {
  mock();
  render(<InboxPage apiKey={null} me={null} isMobile={false} />);
  expect(screen.getByText(/Sign in, or connect an agent key/)).toBeInTheDocument();
});

test('a site account the engine does not know yet gets an explanation, not an error', async () => {
  global.fetch = jest.fn(async () => ({ ok: false, status: 401, json: async () => ({ ok: false, error: 'authentication required' }) }));
  render(<InboxPage apiKey="site.token" me={null} isMobile={false} onUnreadChange={() => {}} />);
  expect(await screen.findByText(/Your inbox starts once you've confirmed your email/)).toBeInTheDocument();
});
