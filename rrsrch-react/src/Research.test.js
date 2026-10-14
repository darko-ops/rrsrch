import { render, screen, fireEvent } from '@testing-library/react';
import { ExplorePage, PostPage } from './Research';
import ClaimPage from './ClaimPage';

const FEED = {
  ok: true, next_offset: null, topics: [{ topic: 'msc', posts: 2 }],
  items: [
    { id: 2, repository: 'rrsrch/network', author: 'ext', author_kind: 'human', kind: 'question', status: 'open',
      title: 'Does the effect hold past 24 months?', excerpt: 'Looking for long follow-up.', topics: ['msc'],
      created_at: '2026-10-14T00:00:00Z', comments: 0, reports: 0, reactions: 0 },
    { id: 1, repository: 'rrsrch/network', author: 'bot', author_kind: 'service', kind: 'finding', status: 'open',
      title: 'WOMAC gains at 12 months', excerpt: 'See the trial.', topics: ['msc'],
      created_at: '2026-10-13T00:00:00Z', comments: 1, reports: 1, reactions: 5 },
  ],
};
const REPORTS = {
  note: 'evidence for reviewers; a report never changes review state by itself',
  summary: { reproduction: { reproduced: 1, failed: 0, inconclusive: 0, insufficient_evidence: 0, independent: 1 },
    usage: { worked: 0, worked_with_conditions: 0, failed: 0, outdated: 0, missing_step: 0, unclear: 0, independent: 0 } },
  items: [{ id: 4, context: 'reproduction', outcome: 'reproduced', author: 'lab-agent', author_kind: 'service',
    independent: true, method: 'Reanalysis', environment: '', observations: 'Same effect size.', conditions: '',
    limitations: 'n=40', versions: {}, artifacts: [{ name: 'nb', url: 'https://example.org/nb' }], revision: null,
    created_at: '2026-10-14T00:00:00Z' }],
};
const POST = {
  ok: true, promoted: null, comments: [], verification: REPORTS,
  reactions: { counts: { useful: 0, interesting: 0, needs_clarification: 0 }, mine: [] },
  post: { id: 1, repository: 'rrsrch/network', author: 'bot', author_kind: 'service', kind: 'finding', status: 'open',
    title: 'WOMAC gains at 12 months', body: 'See the trial.', topics: ['msc'], created_at: '2026-10-13T00:00:00Z',
    evidence: [{ source_id: 'MED:1', doc_sha256: 'a'.repeat(64), start: 0, end: 10, excerpt: 'At 12 months',
      source_title: 'BM-MSC trial' }] },
};

function mock(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const hit = Object.keys(routes).find((k) => url.includes(k));
    return { ok: true, status: 200, json: async () => (hit ? routes[hit] : { ok: true }) };
  });
  return calls;
}

beforeEach(() => localStorage.setItem('rrsrch_engine_key', 'rrsrch_k'));
afterEach(() => localStorage.clear());

test('explore lists posts in the order the engine gives, with filters and topic follows', async () => {
  const calls = mock({ '/v1/explore': FEED });
  render(<ExplorePage isMobile={false} />);
  const titles = await screen.findAllByText(/WOMAC gains|Does the effect/);
  expect(titles.map((t) => t.textContent)).toEqual(['Does the effect hold past 24 months?', 'WOMAC gains at 12 months']);
  expect(screen.getByText(/not reviewed knowledge/)).toBeInTheDocument();
  expect(calls[0].url).toBe('/api/engine/v1/explore?sort=recent&limit=20');
  fireEvent.click(screen.getByText('questions'));
  fireEvent.click(screen.getByText('recently active'));
  fireEvent.click(screen.getByRole('button', { name: /#msc/ }));
  fireEvent.click(await screen.findByText('Follow #msc'));
  await screen.findByText(/Following #msc/);
  expect(calls.some((c) => c.url === '/api/engine/v1/explore?sort=active&limit=20&kind=question&topic=msc')).toBe(true);
  const sub = calls.find((c) => c.url === '/api/engine/v1/subscriptions');
  expect(JSON.parse(sub.opts.body)).toEqual({ target: 'topic:msc' });
});

test('publishing a post sends kind, title, body and topics', async () => {
  const calls = mock({ '/v1/explore': FEED, '/v1/posts': { ok: true, post_id: 9 } });
  render(<ExplorePage isMobile={false} />);
  fireEvent.click(await screen.findByText('New post'));
  fireEvent.click(screen.getByText('observation'));
  fireEvent.change(screen.getByPlaceholderText('Title'), { target: { value: 'Dose matters' } });
  fireEvent.change(screen.getByPlaceholderText(/What did you find/), { target: { value: 'Higher doses did better.' } });
  fireEvent.change(screen.getByPlaceholderText(/Topics/), { target: { value: 'msc, dosing' } });
  fireEvent.click(screen.getByText('Publish'));
  await new Promise((r) => setTimeout(r, 0));
  const pub = calls.find((c) => c.url === '/api/engine/v1/posts');
  expect(JSON.parse(pub.opts.body)).toEqual({ kind: 'observation', title: 'Dose matters', body: 'Higher doses did better.',
    topics: ['msc', 'dosing'] });
  expect(window.location.hash).toBe('#/posts/9');
});

test('a post shows its evidence and reports, and promotes through a merge request', async () => {
  const calls = mock({ '/v1/posts/1/promote': { ok: true, merge_request_id: 7 }, '/v1/posts/1': POST });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText('“At 12 months”')).toBeInTheDocument();
  expect(screen.getByText('Same effect size.')).toBeInTheDocument();
  expect(screen.getByText(/never changes review state by itself/)).toBeInTheDocument();
  expect(screen.getByText('reproduced · 1')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Propose as a claim'));
  fireEvent.change(screen.getByPlaceholderText(/Repository/), { target: { value: 'rrsrch/msc-knee-oa' } });
  fireEvent.click(screen.getByText('Open merge request'));
  await new Promise((r) => setTimeout(r, 0));
  const promote = calls.find((c) => c.url === '/api/engine/v1/posts/1/promote');
  expect(JSON.parse(promote.opts.body)).toEqual({ repository: 'rrsrch/msc-knee-oa',
    proposition: 'WOMAC gains at 12 months', type: 'empirical' });
});

test('usage reports go to the engine with their context and outcome', async () => {
  const calls = mock({ '/v1/verifications': { ok: true, report_id: 3 }, '/v1/posts/1': POST });
  render(<PostPage postId={1} isMobile={false} />);
  fireEvent.click(await screen.findByText('Report a reproduction or use'));
  fireEvent.change(screen.getByLabelText('outcome'), { target: { value: 'missing_step' } });
  fireEvent.change(screen.getByPlaceholderText(/What did you do/), { target: { value: 'Dose was not stated.' } });
  fireEvent.change(screen.getByPlaceholderText(/Link to an artifact/), { target: { value: 'https://example.org/run.log' } });
  fireEvent.click(screen.getByText('Submit report'));
  await new Promise((r) => setTimeout(r, 0));
  const rep = calls.find((c) => c.url === '/api/engine/v1/verifications');
  expect(JSON.parse(rep.opts.body)).toEqual({ target: 'post:1', context: 'usage', outcome: 'missing_step',
    observations: 'Dose was not stated.', method: '', environment: '', conditions: '', limitations: '',
    artifacts: [{ name: 'run.log', url: 'https://example.org/run.log' }] });
});

test('the claim page lists reproduction and usage reports under its formal standing', async () => {
  mock({ '/feedback': {
    ok: true,
    claim: { id: 12, repository: 'rrsrch/msc-knee-oa', type: 'empirical', state: 'under_review', contributor: 'rrsrch-reader',
      proposition: 'WOMAC improved.', evidence: [] },
    formal: { note: 'decided by policy', state: 'under_review', verification: null, reviews: [], challenges: [],
      contradicted_by: [], verification_reports: REPORTS },
    informal: { note: 'reactions never change state', reactions: { counts: {}, mine: [] }, comments: [] },
  } });
  render(<ClaimPage claimId={12} isMobile={false} />);
  expect(await screen.findByText('Reproduction and use')).toBeInTheDocument();
  expect(screen.getByText('Same effect size.')).toBeInTheDocument();
});
