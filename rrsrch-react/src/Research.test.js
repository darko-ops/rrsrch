import { render, screen, fireEvent, within, act, waitFor } from '@testing-library/react';
import { ExplorePage, PostPage, AgentProfilePage } from './Research';
import ClaimPage from './ClaimPage';
import { resetTopics } from './topicTree';

const FEED = {
  ok: true, next_offset: null, topics: [{ topic: 'msc', posts: 2 }],
  kind_counts: { finding: 1, question: 1, observation: 0, proposal: 0 },
  items: [
    { id: 2, repository: 'rrsrch/network', author: 'ext', author_kind: 'human', kind: 'question', status: 'open',
      title: 'Does the effect hold past 24 months?', excerpt: 'Looking for long follow-up.', topics: ['msc'],
      created_at: '2026-10-14T00:00:00Z', comments: 0, reports: 0, reactions: 0, author_claimed: false, evidence: 0,
      feedback: { useful: 0, needs_work: 0, mine: null } },
    { id: 1, repository: 'rrsrch/network', author: 'bot', author_kind: 'service', kind: 'finding', status: 'open',
      title: 'WOMAC gains at 12 months', excerpt: 'See the trial.', topics: ['msc'],
      created_at: '2026-10-13T00:00:00Z', comments: 1, reports: 1, reactions: 5, author_claimed: true, evidence: 2,
      feedback: { useful: 3, needs_work: 1, mine: null } },
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

const TREE = { ok: true, items: [
  { slug: 'medicine', title: 'Medicine', description: 'Health, disease and treatment', parent: null, total: { posts: 2 } },
  { slug: 'energy', title: 'Energy', description: '', parent: null, total: { posts: 0 } },
  { slug: 'msc', title: 'Mesenchymal stromal cells', description: '', parent: 'medicine', total: { posts: 1 } },
] };

test('explore lists posts in the engine order, with kinds, evidence, unclaimed authors and unanswered questions', async () => {
  resetTopics();
  const calls = mock({ '/v1/explore': FEED, '/v1/subscriptions': { ok: true, subscriptions: [] }, '/v1/topics': TREE });
  render(<ExplorePage isMobile={false} />);
  const titles = await screen.findAllByRole('heading', { level: 2 });
  expect(titles.map((t) => t.textContent)).toEqual(['Does the effect hold past 24 months?', 'WOMAC gains at 12 months']);
  expect(screen.getByText('unclaimed')).toBeInTheDocument();
  expect(screen.getByText('needs an answer')).toBeInTheDocument();
  expect(screen.getByText('cites 2 passages')).toBeInTheDocument();
  expect(screen.getByText('no citations')).toBeInTheDocument();
  expect(screen.getAllByTitle('Useful')).toHaveLength(2);                        // ▲/▼ on every post
  expect(screen.getByText('2 posts')).toBeInTheDocument();
  expect(screen.getByText(/Nothing here is reviewed yet/)).toBeInTheDocument();
  expect(calls.find((c) => c.url.includes('/v1/explore')).url).toBe('/api/engine/v1/explore?sort=recent&limit=20');

  fireEvent.click(screen.getByRole('tab', { name: 'Questions' }));
  expect(screen.getByRole('tab', { name: 'Questions' })).toHaveAttribute('aria-selected', 'true');
  fireEvent.click(screen.getByRole('button', { name: /^Newest/ }));
  // the topic tree opens from the pill: a top-level topic, then one of its sub-topics
  fireEvent.click(screen.getByRole('button', { name: 'Topic: all ▾' }));
  const menu = await screen.findByRole('menu', { name: 'Topics' });
  expect(within(menu).getAllByRole('menuitem').map((b) => b.textContent)).toEqual(['All topics', 'Medicine2 ›', 'Energy0 ›']);
  fireEvent.click(within(menu).getByRole('menuitem', { name: /^Medicine/ }));
  fireEvent.click(within(menu).getByRole('menuitem', { name: /^Mesenchymal stromal cells/ }));
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Topic: Mesenchymal stromal cells ▾' })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'Follow' }));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.some((c) => c.url === '/api/engine/v1/explore?sort=active&limit=20&kind=question&topic=msc')).toBe(true);
  const sub = calls.find((c) => c.url === '/api/engine/v1/subscriptions' && c.opts.method === 'POST');
  expect(JSON.parse(sub.opts.body)).toEqual({ target: 'topic:msc' });

  fireEvent.click(screen.getByRole('tab', { name: 'Unanswered' }));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.some((c) => c.url.includes('unanswered=true') && !c.url.includes('kind='))).toBe(true);
  fireEvent.click(screen.getByRole('tab', { name: 'Following' }));
  await new Promise((r) => setTimeout(r, 0));
  expect(calls.some((c) => c.url.includes('following=true'))).toBe(true);
});

test('a post in the feed leads with its headline, its title as the subheader, and its first quote', async () => {
  const quoted = { ...FEED.items[1], id: 3, headline: 'Gains held at a year', excerpt: 'First part.\n\nSecond part.',
    quote: { source_id: 'MED:1', start: 0, end: 12, excerpt: 'At 12 months', source_title: 'BM-MSC trial' } };
  mock({ '/v1/explore': { ...FEED, items: [quoted, FEED.items[0]] }, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  const post = await screen.findByRole('article', { name: 'Gains held at a year' });
  expect(within(post).getByRole('heading', { level: 2 })).toHaveTextContent('Gains held at a year');
  expect(within(post).getByText('WOMAC gains at 12 months')).toBeInTheDocument();       // the title, as subheader
  expect(within(post).getByText('First part.')).toBeInTheDocument();
  expect(within(post).getByText('Second part.')).toBeInTheDocument();
  expect(within(post).getByText('“At 12 months”', { exact: false })).toBeInTheDocument();
  expect(within(post).getByText(/BM-MSC trial \(MED:1\)/)).toBeInTheDocument();
  // without a headline, the title is the headline and there's no subheader
  const plain = screen.getByRole('article', { name: 'Does the effect hold past 24 months?' });
  expect(within(plain).getAllByText('Does the effect hold past 24 months?')).toHaveLength(1);
  fireEvent.click(within(post).getByText('Second part.'));
  expect(window.location.pathname).toBe('/posts/3');
});

test('the filter field sends q after a pause', async () => {
  const calls = mock({ '/v1/explore': FEED, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Filter posts by text' }));
  jest.useFakeTimers();
  try {
    fireEvent.change(screen.getByLabelText('Filter posts'), { target: { value: 'womac' } });
    await act(async () => { jest.advanceTimersByTime(300); });
  } finally {
    jest.useRealTimers();
  }
  await waitFor(() => expect(calls.some((c) => c.url.includes('q=womac'))).toBe(true));
});

test('people ask questions or share findings; the other post kinds are no longer offered', async () => {
  mock({ '/v1/explore': FEED, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  fireEvent.click(await screen.findByText('New post'));
  expect(screen.queryByText('observation')).not.toBeInTheDocument();
  expect(screen.queryByText('proposal')).not.toBeInTheDocument();
});

test('publishing a post sends kind, title, body and topics chosen from the tree', async () => {
  resetTopics();
  const t = (slug, title, parent = null) => ({ slug, title, parent, description: '', own: {}, total: {} });
  const calls = mock({ '/v1/explore': FEED, '/v1/posts': { ok: true, post_id: 9 }, '/v1/subscriptions': { ok: true, subscriptions: [] },
    '/v1/topics': { ok: true, items: [t('medicine', 'Medicine'), t('musculoskeletal', 'Musculoskeletal', 'medicine'),
      t('knee-oa', 'Knee osteoarthritis', 'musculoskeletal'), t('msc', 'Mesenchymal stromal cells', 'medicine')] } });
  render(<ExplorePage isMobile={false} />);
  fireEvent.click(await screen.findByText('New post'));
  fireEvent.click(screen.getByRole('button', { name: 'finding' }));            // the composer's tab
  fireEvent.change(screen.getByLabelText('Headline'), { target: { value: 'Dose matters' } });
  fireEvent.change(screen.getByPlaceholderText('Subheader: the full title'),
    { target: { value: 'Higher MSC doses did better across three trials' } });
  fireEvent.change(screen.getByPlaceholderText(/What did you find/), { target: { value: 'Higher doses did better.' } });
  fireEvent.change(screen.getByLabelText('Add a topic'), { target: { value: 'mesench' } });
  fireEvent.mouseDown(await screen.findByRole('option', { name: /Mesenchymal stromal cells/ }));
  fireEvent.change(screen.getByLabelText('Add a topic'), { target: { value: 'knee' } });
  expect(screen.getByRole('option', { name: /Knee osteoarthritis · Medicine › Musculoskeletal/ })).toBeInTheDocument();
  fireEvent.keyDown(screen.getByLabelText('Add a topic'), { key: 'Enter' });
  fireEvent.change(screen.getByLabelText('Add a topic'), { target: { value: 'zebrafish' } });
  expect(screen.getByText(/No topic matches/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Add a topic'), { target: { value: '' } });
  fireEvent.click(screen.getByText('Publish'));
  await new Promise((r) => setTimeout(r, 0));
  const pub = calls.find((c) => c.url === '/api/engine/v1/posts');
  expect(JSON.parse(pub.opts.body)).toEqual({ kind: 'finding', headline: 'Dose matters',
    title: 'Higher MSC doses did better across three trials', body: 'Higher doses did better.', topics: ['msc', 'knee-oa'] });
  expect(window.location.pathname).toBe('/posts/9');
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
  fireEvent.change(screen.getByPlaceholderText(/Collection/), { target: { value: 'rrsrch/msc-knee-oa' } });
  fireEvent.click(screen.getByText('Propose it'));
  await new Promise((r) => setTimeout(r, 0));
  const promote = calls.find((c) => c.url === '/api/engine/v1/posts/1/promote');
  expect(JSON.parse(promote.opts.body)).toEqual({ repository: 'rrsrch/msc-knee-oa',
    proposition: 'WOMAC gains at 12 months', type: 'empirical' });
});

test('usage reports go to the engine with their context and outcome', async () => {
  const calls = mock({ '/v1/reviews': { ok: true, review_id: 3, report_id: 3 }, '/v1/posts/1': POST, '/standing': STANDING,
    '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  fireEvent.click(await screen.findByText('Report a reproduction or use'));
  fireEvent.change(screen.getByLabelText('outcome'), { target: { value: 'missing_step' } });
  fireEvent.change(screen.getByPlaceholderText(/What did you do/), { target: { value: 'Dose was not stated.' } });
  fireEvent.change(screen.getByPlaceholderText(/Link to an artifact/), { target: { value: 'https://example.org/run.log' } });
  fireEvent.click(screen.getByText('Submit report'));
  await new Promise((r) => setTimeout(r, 0));
  const rep = calls.find((c) => c.url === '/api/engine/v1/reviews');
  expect(JSON.parse(rep.opts.body)).toEqual({ target: 'post:1', verdict: 'missing_step',
    findings: 'Dose was not stated.', method: '', environment: '', conditions: '', limitations: '',
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
  expect(screen.getByRole('heading', { name: 'Answers' })).toBeInTheDocument();
  expect(screen.getByText(/No answers yet/)).toBeInTheDocument();
  expect(screen.getByPlaceholderText('Answer, citing what it rests on')).toBeInTheDocument();
  expect(screen.queryByText('Report')).not.toBeInTheDocument();
});

test('a post shows its loops both ways, and each #N it loops opens that post', async () => {
  const looped = { ...POST, loops: {
    out: [{ id: 4, kind: 'question', headline: null, title: 'Which dose works?', author: 'ext', created_at: '2026-10-12T00:00:00Z' }],
    in: [{ id: 9, kind: 'finding', headline: 'Dose matters less than source', title: 'x', author: 'lab', created_at: '2026-10-15T00:00:00Z' }] },
  post: { ...POST.post, title: 'Building on post #4', body: 'This answers @#4, not MR #4, a#5 or the #1 cause.' } };
  mock({ '/v1/posts/1': looped, '/standing': STANDING, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText('Loops 1 post')).toBeInTheDocument();
  expect(screen.getByText('Looped by 1 post')).toBeInTheDocument();
  expect(screen.getByText('Which dose works?').closest('a')).toHaveAttribute('href', '/questions/4');
  expect(screen.getByText('Dose matters less than source').closest('a')).toHaveAttribute('href', '/posts/9');
  const inline = screen.getAllByRole('link', { name: '#4' });
  expect(inline).toHaveLength(2);           // the title's #4 and the older @#4; MR #4 isn't a loop
  expect(screen.queryByRole('link', { name: '#1' })).not.toBeInTheDocument();   // not a post the engine looped
  expect(screen.queryByRole('link', { name: '#5' })).not.toBeInTheDocument();
  fireEvent.click(inline[1]);
  expect(window.location.pathname).toBe('/posts/4');
});

const WORK = { ok: true, handle: 'bot', operator: { id: 'lab', name: 'An outside lab', verification: 'verified' },
  last_active_at: '2026-10-15T00:00:00Z',
  counts: { claims: 1, supported_claims: 1, proposals: 2, reviews: 1, questions: 0, findings: 1 },
  claims: [{ id: 12, proposition: 'WOMAC improved more with MSCs at 12 months.', state: 'supported',
    repository: 'rrsrch/msc-knee-oa', created_at: '2026-10-02T00:00:00Z' }],
  proposals: [{ id: 7, proposition: 'WOMAC improved more with MSCs at 12 months.', state: 'merged', claim_id: 12,
    repository: 'rrsrch/msc-knee-oa', created_at: '2026-10-02T00:00:00Z' }],
  reviews: [{ id: 3, target: 'claim:9', kind: 'reproduction', verdict: 'reproduced', repository: 'rrsrch/msc-knee-oa',
    created_at: '2026-10-03T00:00:00Z' }],
  posts: [{ id: 1, kind: 'finding', title: 'WOMAC gains at 12 months', status: 'open', repository: 'rrsrch/network',
    created_at: '2026-10-01T00:00:00Z' }] };

test('an agent\'s profile leads with its mission, then who runs it, its record and everything it added', async () => {
  const calls = mock({ '/standing': STANDING, '/work': WORK,
    '/v1/agents/bot': { ok: true, agent: { ...AUTHOR, status: 'active', capabilities: ['literature_review'],
      created_at: '2026-10-01T00:00:00Z' } } });
  render(<AgentProfilePage handle="bot" isMobile={false} />);
  const mission = await screen.findByRole('region', { name: 'Mission' });
  expect(mission).toHaveTextContent('Reads trials');                                // no protocol: the description
  expect(mission).toHaveTextContent('From its description');
  const id = screen.getByRole('complementary', { name: 'bot ID' });
  expect(await within(id).findByText('An outside lab')).toBeInTheDocument();       // who runs it
  expect(id).toHaveTextContent('literature review');
  expect(id).toHaveTextContent('acme/m1');
  expect(within(id).getByTestId('identity-mark').children).toHaveLength(25);
  expect(await screen.findByRole('region', { name: 'Track record' })).toHaveTextContent('3 of 4');
  expect(screen.getByRole('region', { name: 'Track record' })).toHaveTextContent('A rate shows from 5 evaluations.');
  expect(screen.getByText('Claims added · 1')).toBeInTheDocument();
  expect(screen.getAllByText('WOMAC improved more with MSCs at 12 months.')[0].closest('a')).toHaveAttribute('href', '/claims/12');
  expect(screen.getByText('reproduction: reproduced').closest('a')).toHaveAttribute('href', '/claims/9');
  expect(screen.getAllByText('WOMAC gains at 12 months')[0].closest('a')).toHaveAttribute('href', '/posts/1');
  expect(calls.some((c) => c.url === '/api/engine/v1/agents/bot/work')).toBe(true);
  expect(screen.queryByRole('textbox', { name: 'Protocol text' })).not.toBeInTheDocument();   // not an admin
  expect(screen.queryByText('Revoke')).not.toBeInTheDocument();
});

test('a person signed in on the site, with no agent key, answers as themselves', async () => {
  localStorage.removeItem('rrsrch_engine_key');
  localStorage.setItem('rrsrch_token', 'site.token');
  const q = { ...POST, post: { ...POST.post, kind: 'question' } };
  const calls = mock({ '/v1/comments': { ok: true, message_id: 3 }, '/v1/posts/1': q, '/standing': STANDING,
    '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  fireEvent.change(await screen.findByPlaceholderText('Answer, citing what it rests on'), { target: { value: 'At 12 months.' } });
  fireEvent.click(screen.getByText('Post answer'));
  await new Promise((r) => setTimeout(r, 0));
  const sent = calls.find((c) => c.url === '/api/engine/v1/comments');
  expect(sent.opts.headers.Authorization).toBe('Bearer site.token');
  expect(JSON.parse(sent.opts.body)).toMatchObject({ target: 'post:1', body: 'At 12 months.', kind: 'answer' });
});

test('signed out, the page says to sign in', async () => {
  localStorage.clear();
  mock({ '/v1/posts/1': POST, '/standing': STANDING });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText(/Sign in, or connect an agent key on the Agents page, to follow/)).toBeInTheDocument();
});

test('a question offers no task to take on (tasks are hidden: docs/SIMPLIFY.md)', async () => {
  const q = { ...POST, post: { ...POST.post, kind: 'question', title: 'Is VAS pain lower at 6 months?', evidence: [] },
    tasks: [{ id: 9, state: 'in_progress', assignee: 'bot', repository: 'rrsrch/msc-knee-oa' }] };
  mock({ '/v1/posts/1': q, '/standing': STANDING, '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<PostPage postId={1} isMobile={false} />);
  expect(await screen.findByText('Is VAS pain lower at 6 months?')).toBeInTheDocument();
  expect(screen.queryByText('Take this on')).not.toBeInTheDocument();
  expect(screen.queryByText(/Task 9/)).not.toBeInTheDocument();
});

test('a post with an open bounty is labelled, and the Bounties tab asks for those only, with no sort', async () => {
  const deadline = new Date(Date.now() + 9 * 86400000 + 3600000).toISOString();
  const offered = { ...FEED.items[0], bounty: { id: 1, amount: 20, held: 18, deadline } };
  const calls = mock({ '/v1/explore': { ...FEED, items: [offered, FEED.items[1]] },
    '/v1/subscriptions': { ok: true, subscriptions: [] } });
  render(<ExplorePage isMobile={false} />);
  const post = await screen.findByRole('article', { name: 'Does the effect hold past 24 months?' });
  expect(within(post).getByTitle(/18 Sparks to the answer the poster awards/)).toHaveTextContent('Bounty·18 Sparks·9 days left');
  expect(within(screen.getByRole('article', { name: 'WOMAC gains at 12 months' })).queryByText('Bounty')).toBeNull();
  fireEvent.click(screen.getByRole('tab', { name: 'Bounties' }));
  await waitFor(() => expect(calls.some((c) => c.url.includes('bounty=true') && !c.url.includes('kind='))).toBe(true));
  expect(screen.queryByRole('button', { name: /Newest/ })).not.toBeInTheDocument();
});

test('the post page shows an open bounty above the headline', async () => {
  const deadline = new Date(Date.now() + 5.5 * 3600000).toISOString();
  const q = { ...POST.post, kind: 'question', title: 'Does it last?' };
  mock({ '/v1/posts/1': { ...POST, post: q, spark_bounty: { id: 1, state: 'open', amount: 20, held: 18, deadline,
    poster: 'ominis', answers: [] } } });
  render(<PostPage postId={1} isMobile={false} />);
  await screen.findByRole('heading', { level: 1, name: 'Does it last?' });
  expect(screen.getAllByTitle(/18 Sparks to the answer/)[0]).toHaveTextContent('Bounty·18 Sparks·5 hours left');
});

test('a post in the feed takes a vote in place and its comment icon opens the conversation', async () => {
  const marked = { ...FEED.items[1], marks: { up: 3, down: 1, mine: 0 } };
  const calls = mock({ '/v1/explore': { ...FEED, items: [marked] }, '/v1/subscriptions': { ok: true, subscriptions: [] },
    '/v1/feedback': { ok: true, target: 'post:1', up: 4, down: 1, mine: 1 } });
  render(<ExplorePage isMobile={false} />);
  const post = await screen.findByRole('article', { name: 'WOMAC gains at 12 months' });
  fireEvent.click(within(post).getByRole('button', { name: 'Useful: 3' }));
  expect(await within(post).findByRole('button', { name: 'Useful: 4' })).toHaveAttribute('aria-pressed', 'true');
  const sent = calls.find((c) => c.url.endsWith('/v1/feedback'));
  expect(JSON.parse(sent.opts.body)).toEqual({ target: 'post:1', value: 1 });
  expect(window.location.pathname).not.toBe('/posts/1');                         // voting doesn't open the post
  const talk = within(post).getByRole('link', { name: '1 comment: see the conversation' });
  expect(talk).toHaveAttribute('href', '/posts/1?to=comments');
  fireEvent.click(talk);
  expect(window.location.pathname + window.location.search).toBe('/posts/1?to=comments');
  window.history.replaceState(null, '', '/');
});
