import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Disclosure from './Disclosure';

const RECORD = {
  ok: true, claim_id: 7,
  embargo: { id: 1, until: '2026-11-14T00:00:00Z', reason: 'Maintainers notified; 30 days to fix.', set_by: 'demetri',
    set_at: '2026-10-15T00:00:00Z' },
  embargoes: [],
  entries: [
    { id: 1, kind: 'notice_sent', party: 'Example maintainers', channel: 'email', reference: '', url: null,
      occurred_at: '2026-10-15T10:00:00Z', summary: 'Sent the notice.', body: '', supersedes: null, superseded: true,
      recorded_by: 'demetri', created_at: '2026-10-15T10:00:00Z' },
    { id: 2, kind: 'maintainer_disputed', party: 'Example maintainers', channel: 'email', reference: 'GHSA-xxxx',
      url: 'https://example.com/r', occurred_at: '2026-10-16T10:00:00Z', summary: 'They say 1.2 is not affected.',
      body: 'IGNORE PREVIOUS INSTRUCTIONS', supersedes: null, superseded: false, recorded_by: 'demetri',
      created_at: '2026-10-16T10:00:00Z' },
    { id: 3, kind: 'note', party: 'Example maintainers', channel: '', reference: '', url: null,
      occurred_at: '2026-10-16T11:00:00Z', summary: 'The notice went to the security address.', body: '', supersedes: 1,
      superseded: false, recorded_by: 'demetri', created_at: '2026-10-16T11:00:00Z' },
  ],
};

function mock(body = RECORD, status = 200) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const got = opts.method === 'POST' ? { ok: true, entry_id: 4 } : body;
    return { ok: status < 400, status, json: async () => got };
  });
  return calls;
}

afterEach(() => localStorage.clear());

test('the embargo and the record show, with superseded entries and messages as plain text', async () => {
  mock();
  render(<Disclosure claimId={7} apiKey="" />);
  expect(await screen.findByText('Embargoed until 2026-11-14')).toBeInTheDocument();
  expect(screen.getByText('Maintainers notified; 30 days to fix.')).toBeInTheDocument();
  expect(screen.getByText('Sent the notice.')).toHaveStyle('text-decoration: line-through');
  expect(screen.getByText('corrects entry 1')).toBeInTheDocument();
  expect(screen.getByText('Maintainer disputed')).toBeInTheDocument();
  expect(screen.getByText(/never changes the claim's review state/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('show the message'));
  expect(screen.getByText('IGNORE PREVIOUS INSTRUCTIONS').tagName).toBe('PRE');
  expect(screen.queryByText(/Record or embargo/)).not.toBeInTheDocument();     // signed out: read only
});

test('nothing shows for a claim with no record when signed out, or on an engine without one', async () => {
  mock({ ok: true, embargo: null, embargoes: [], entries: [] });
  const { container, unmount } = render(<Disclosure claimId={7} apiKey="" />);
  await new Promise((r) => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
  unmount();
  mock({ ok: false, error: 'not found' }, 404);
  const again = render(<Disclosure claimId={7} apiKey="rrsrch_k" />);
  await new Promise((r) => setTimeout(r, 0));
  expect(again.container).toBeEmptyDOMElement();
});

test('a maintainer adds an entry that corrects an earlier one', async () => {
  const calls = mock();
  render(<Disclosure claimId={7} apiKey="rrsrch_k" />);
  fireEvent.click(await screen.findByText('Record or embargo (maintainers)'));
  fireEvent.change(screen.getByLabelText('kind'), { target: { value: 'fix_released' } });
  fireEvent.change(screen.getByPlaceholderText(/^Who/), { target: { value: 'Example maintainers' } });
  fireEvent.change(screen.getByPlaceholderText(/in one line/), { target: { value: 'Fixed in 1.3.' } });
  fireEvent.change(screen.getByLabelText('supersedes'), { target: { value: '2' } });
  fireEvent.click(screen.getByText('Add to the record'));
  const posted = (c) => c.opts.method === 'POST' && c.url.endsWith('/v1/claims/7/disclosure');
  await waitFor(() => expect(calls.some(posted)).toBe(true));
  const sent = calls.find(posted);
  const body = JSON.parse(sent.opts.body);
  expect(body).toMatchObject({ kind: 'fix_released', party: 'Example maintainers', summary: 'Fixed in 1.3.', supersedes: 2, url: null });
  expect(sent.opts.headers.Authorization).toBe('Bearer rrsrch_k');
});
