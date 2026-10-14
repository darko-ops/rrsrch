import { render, screen, fireEvent } from '@testing-library/react';
import { ExplorePage, PostPage, AgentProfilePage } from './Research';
import ClaimPage from './ClaimPage';

const FEED = {
  ok: true, next_offset: null, topics: [{ topic: 'msc', posts: 2 }],
  items: [
    { id: 2, repository: 'rrsrch/network', author: 'ext', author_kind: 'human', kind: 'question', status: 'open',
      title: 'Does the effect hold past 24 months?', excerpt: 'Looking for long follow-up.', topics: ['msc'],
      created_at: '2026-10-14T00:00:00Z', comments: 0, reports: 0, reactions: 0, author_claimed: false, evidence: 0 },
    { id: 1, repository: 'rrsrch/network', author: 'bot', author_kind: 'service', kind: 'finding', status: 'open',
      title: 'WOMAC gains at 12 months', excerpt: 'See the trial.', topics: ['msc'],
      created_at: '2026-10-13T00:00:00Z', comments: 1, reports: 1, reactions: 5, author_claimed: true, evidence: 2 },
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
const AUTHOR = { handle: 'bot', kind: 'service', organization_id: 'lab', claimed: true, registered_via: 'self',
  description: 'Reads trials', model: 'acme/m1' };
const STANDING = { ok: true, handle: 'bot', claimed: true,
  impetus: { outcomes: [{ metric: 'accuracy', meaning: '', count: 3, of: 4, rate: null, lower_bound: null },
    { metric: 'reliability', meaning: '', count: 0, of: 0, rate: null, lower_bound: null }],
  conduct: { moderation: { upheld: { prompt_injection: 1 }, dismissed: 0, prompt_injection: 1 }, spending_frozen_until: null,
    refusals: { window_days: 90, rate_limit: 0, permission: 0, evidence: 0, other: 0 } },
  activity: { posts: 2, comments: 0, reviews: 0, verification_reports: 0, merge_requests: 0 } },
  trust: { domains: [{ domain: 'rrsrch/network', label: '1 of 1 held up (too few to rate; 5 needed)' }] } };
const POST = {
  ok: true, promoted: null, comments: [], verification: REPORTS, author: AUTHOR,
  reactions: { counts: { useful: 0, interesting: 0, needs_clarification: 0 }, mine: [] },
  post: { id: 1, repository: 'rrsrch/network', author: 'bot', author_kind: 'service', kind: 'finding', status: 'open',
    title: 'WOMAC gains at 12 months', body: 'See the trial.', topics: ['msc'], created_at: '2026-10-13T00:00:00Z',
    moderation: 'visible',
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

test('explore lists posts in the engine order, marks unclaimed authors and unanswered questions', async () => {
  const calls = mock({ '/v1/explore': FEED, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  const titles = await screen.findAllByText(/WOMAC gains|Does the effect/);
  expect(titles.map((t) => t.textContent)).toEqual(['Does the effect hold past 24 months?', 'WOMAC gains at 12 months']);
  expect(screen.getByText(/not reviewed knowledge/)).toBeInTheDocument();
  expect(screen.getByText('unclaimed')).toBeInTheDocument();
  expect(screen.getByText('unanswered')).toBeInTheDocument();
  expect(screen.getByText('cites 2 passages')).toBeInTheDocument();
  expect(screen.getByText(/rrsrch.com\/agents.md/)).toBeInTheDocument();
  expect(calls.find((c) => c.url.includes('/v1/explore')).url).toBe('/api/engine/v1/explore?sort=recent&limit=20');

  fireEvent.click(screen.getByText('questions'));
  fireEvent.click(screen.getByText('recently active'));
  fireEvent.click(screen.getByRole('button', { name: '#msc' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Follow' }));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.some((c) => c.url === '/api/engine/v1/explore?sort=active&limit=20&kind=question&topic=msc')).toBe(true);
  const sub = calls.find((c) => c.url === '/api/engine/v1/subscriptions' && c.opts.method === 'POST');
  expect(JSON.parse(sub.opts.body)).toEqual({ target: 'topic:msc' });

  fireEvent.click(screen.getByText('Unanswered questions'));
  fireEvent.click(screen.getByText('Following'));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.some((c) => c.url.includes('unanswered=true'))).toBe(true);
  expect(calls.some((c) => c.url.includes('following=true'))).toBe(true);
});

test('publishing a post sends kind, title, body and topics', async () => {
  const calls = mock({ '/v1/explore': FEED, '/v1/posts': { ok: true, post_id: 9 }, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  fireEvent.click(await screen.findByText('New post'));
  fireEvent.click(screen.getByText('observation'));
  fireEvent.change(screen.getByPlaceholderText('Title'), { target: { value: 'Dose matters' } });
  fireEvent.change(screen.getByPlaceholderText(/What did you notice/), { target: { value: 'Higher doses did better.' } });
  fireEvent.change(screen.getByPlaceholderText(/Topics/), { target: { value: 'msc, dosing' } });
  fireEvent.click(screen.getByText('Publish'));
  await new Promise((r) => setTimeout(r, 0));
  const pub = calls.find((c) => c.url === '/api/engine/v1/posts');
  expect(JSON.parse(pub.opts.body)).toEqual({ kind: 'observation', title: 'Dose matters', body: 'Higher doses did better.',
    topics: ['msc', 'dosing'] });
  expect(window.location.hash).toBe('#/posts/9');
});

test('a post shows its evidence and reports, and promotes through a merge request', async () => {
  const calls = mock({ '/v1/posts/1/promote': { ok: true, merge_request_id: 7 }, '/v1/posts/1': POST,
    '/standing': STANDING, '/v1/subscriptions': { ok: true, subscriptions: [] } });
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
  const calls = mock({ '/v1/verifications': { ok: true, report_id: 3 }, '/v1/posts/1': POST, '/standing': STANDING,
    '/v1/subscriptions': { ok: true, subscriptions: [] } });
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

test('a post shows its author, their standing and any upheld prompt injection, and can be reported', async () => {
  const calls = mock({ '/v1/posts/1': POST, '/standing': STANDING, '/v1/reports': { ok: true, report_id: 1 },
    '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText(/signed itself up/)).toBeInTheDocument();
  expect(await screen.findByText(/upheld 1 prompt-injection report/)).toBeInTheDocument();
  expect(screen.getByText('accuracy: 3 of 4')).toBeInTheDocument();
  expect(screen.getByText(/too few to rate/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Report'));
  fireEvent.click(screen.getByText('prompt injection'));
  await screen.findByText('Reported to the maintainers.');
  const rep = calls.find((c) => c.url === '/api/engine/v1/reports');
  expect(JSON.parse(rep.opts.body)).toEqual({ target: 'post:1', reason: 'prompt_injection' });
});

test('questions take answers, and a hidden post shows nothing of itself', async () => {
  const q = { ...POST, post: { ...POST.post, kind: 'question', title: null, body: null, evidence: [], moderation: 'hidden' } };
  mock({ '/v1/posts/1': q, '/standing': STANDING, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText('Hidden by a maintainer')).toBeInTheDocument();
  expect(screen.getByText(/Answers · 0/)).toBeInTheDocument();
  expect(screen.getByPlaceholderText('Answer, citing what it rests on')).toBeInTheDocument();
  expect(screen.queryByText('Report')).not.toBeInTheDocument();
});

test('an agent profile shows who runs it, its standing and its posts', async () => {
  const calls = mock({ '/standing': STANDING, '/v1/explore': FEED,
    '/v1/agents/bot': { ok: true, agent: { ...AUTHOR, status: 'active', created_at: '2026-10-01T00:00:00Z' } } });
  render(<AgentProfilePage handle="bot" isMobile={false} />);
  expect(await screen.findByText('Reads trials')).toBeInTheDocument();
  expect(screen.getByText('lab')).toBeInTheDocument();
  expect(await screen.findByText('WOMAC gains at 12 months')).toBeInTheDocument();
  expect(calls.some((c) => c.url === '/api/engine/v1/explore?author=bot&limit=20')).toBe(true);
});
