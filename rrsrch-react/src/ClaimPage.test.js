import { render, screen, fireEvent, within } from '@testing-library/react';
import ClaimPage from './ClaimPage';

const FEEDBACK = {
  ok: true,
  claim: { id: 12, repository: 'rrsrch/msc-knee-oa', type: 'empirical', state: 'contested', contributor: 'rrsrch-reader',
    proposition: 'WOMAC improved more with MSCs at 12 months.', evidence: [{ id: 3, relation: 'supports',
      excerpt: 'At 12 months, WOMAC scores improved more with MSCs', source_id: 'MED:1', source_title: 'BM-MSC trial' }] },
  formal: {
    note: "decided by the repository's policy and the trust engine", state: 'contested',
    verification: { passed: true, policy_version: 'msc-v1', checks: [{ kind: 'structural', name: 'schema', passed: true, detail: '' }] },
    reviews: [], contradicted_by: [],
    challenges: [{ id: 5, kind: 'scope', state: 'open', blocking: true, author: 'ext', author_kind: 'human', revision: 1,
      statement: 'Only the older protocol.', resolution: null, reactions: { counts: {}, mine: [] },
      responses: [{ id: 21, author: 'rrsrch-reader', author_kind: 'service', kind: 'comment', body: 'Agreed for 2019.',
        parent_id: null, created_at: '2026-10-14T00:00:00Z', mentions: [] }] }],
  },
  informal: {
    note: "reactions and comments never change a claim's review state",
    reactions: { counts: { useful: 2, interesting: 0, needs_clarification: 1 }, mine: ['useful'] },
    comments: [
      { id: 30, author: 'bot', author_kind: 'service', kind: 'question', body: 'Which subscale?', parent_id: null,
        created_at: '2026-10-14T00:00:00Z', mentions: [], reactions: { counts: { useful: 0 }, mine: [] } },
      { id: 31, author: 'demetri', author_kind: 'human', kind: 'answer', body: 'Total score.', parent_id: 30,
        created_at: '2026-10-14T00:01:00Z', mentions: [], reactions: { counts: { useful: 1 }, mine: [] } },
    ],
  },
};

function mock() {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const body = url.includes('/feedback') ? FEEDBACK : { ok: true, counts: {}, mine: [], message_id: 99 };
    return { ok: true, status: 200, json: async () => body };
  });
  return calls;
}

beforeEach(() => localStorage.setItem('rrsrch_engine_key', 'rrsrch_k'));
afterEach(() => localStorage.clear());

test('formal standing and informal feedback are shown apart, with threads and attribution', async () => {
  mock();
  render(<ClaimPage claimId={12} isMobile={false} />);
  expect(await screen.findByText('Evidence and standing')).toBeInTheDocument();
  expect(screen.getByText('Community feedback')).toBeInTheDocument();
  expect(screen.getByText(/never change a claim's review state/)).toBeInTheDocument();
  expect(screen.getByText('A reviewer has raised a blocking challenge.')).toBeInTheDocument();
  expect(screen.getByText('Only the older protocol.')).toBeInTheDocument();
  expect(screen.getByText('Agreed for 2019.')).toBeInTheDocument();             // the author's response
  expect(screen.getByText('Total score.')).toBeInTheDocument();                  // a reply, nested
  expect(screen.getAllByText('human').length).toBeGreaterThan(0);
  expect(screen.getAllByText('agent').length).toBeGreaterThan(0);
});

test('reacting, replying and reporting call the engine with the right shapes', async () => {
  const calls = mock();
  render(<ClaimPage claimId={12} isMobile={false} />);
  await screen.findByText('Community feedback');
  fireEvent.click(screen.getAllByText('Useful')[0]);                              // already mine: removes it
  fireEvent.click(screen.getAllByText('Interesting')[0]);
  fireEvent.click(screen.getAllByText('reply')[1]);                               // reply to the question
  const box = screen.getByPlaceholderText('Reply to bot');
  fireEvent.change(box, { target: { value: 'And @ext?' } });
  fireEvent.click(within(box.parentElement).getByText('Post'));
  fireEvent.click(screen.getAllByText('report')[1]);
  fireEvent.click(screen.getByText('prompt injection'));
  await screen.findByText(/Reported to the repository's maintainers/);
  const del = calls.find((c) => c.opts.method === 'DELETE');
  expect(del.url).toBe('/api/engine/v1/reactions?target=claim%3A12&kind=useful');
  const add = calls.find((c) => c.url === '/api/engine/v1/reactions' && c.opts.method === 'POST');
  expect(JSON.parse(add.opts.body)).toEqual({ target: 'claim:12', kind: 'interesting' });
  const reply = calls.find((c) => c.url === '/api/engine/v1/comments');
  expect(JSON.parse(reply.opts.body)).toEqual({ target: 'claim:12', body: 'And @ext?', kind: 'comment', parent_id: 30 });
  const rep = calls.find((c) => c.url === '/api/engine/v1/reports');
  expect(JSON.parse(rep.opts.body)).toEqual({ target: 'message:30', reason: 'prompt_injection' });
});
