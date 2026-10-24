import { render, screen, fireEvent, within } from '@testing-library/react';
import SearchExperience from './SearchExperience';

const CLAIMS = { items: [{ id: 898, repository: 'rrsrch/msc-knee-oa', type: 'empirical', state: 'supported',
  proposition: 'VAS pain was lower with MSCs at 12 months.', rank: 0.3, highlight: 'VAS [pain] was lower' }] };
const POSTS = { topics: [], items: [{ id: 5, kind: 'question', title: 'Do MSC trials report pain at 24 months?',
  excerpt: 'Looking for long follow-up.', status: 'open', created_at: '2026-10-14T00:00:00Z', author: 'demetri',
  comments: 2, evidence: 0, topics: [], repository: 'rrsrch/network' }] };

function serve({ claims = CLAIMS, posts = POSTS } = {}, calls = []) {
  global.fetch = jest.fn((url, opts = {}) => {
    calls.push([url, opts]);
    const body = url.startsWith('/api/engine/v1/search?') ? claims
      : url.startsWith('/api/engine/v1/explore?') ? posts
        : url === '/api/engine/v1/posts' ? { post_id: 41 } : null;
    return Promise.resolve({ ok: !!body, status: body ? 200 : 404,
      json: () => Promise.resolve(body ? { ok: true, ...body } : { ok: false, error: 'not found' }) });
  });
  return calls;
}

const search = (text) => {
  const box = screen.getByPlaceholderText('Search claims and questions, or ask the network');
  fireEvent.change(box, { target: { value: text } });
  fireEvent.submit(box.closest('form'));
};

afterEach(() => localStorage.clear());

test('the home search finds claims and posts, and never asks a model or the web', async () => {
  const calls = serve();
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} />);
  search('MSC knee pain');
  const claims = await screen.findByRole('region', { name: 'Claims' });
  expect((await within(claims).findByText('VAS pain was lower with MSCs at 12 months.')).closest('a')).toHaveAttribute('href', '/claims/898');
  expect(claims).toHaveTextContent('supported');
  const posts = screen.getByRole('region', { name: 'Questions and findings' });
  expect(within(posts).getByText('Do MSC trials report pain at 24 months?').closest('a')).toHaveAttribute('href', '/questions/5');
  expect(posts).toHaveTextContent('2 answers');
  expect(screen.getByText(/Nothing here is generated for your search/)).toBeInTheDocument();
  const urls = calls.map(([u]) => u);
  expect(urls.some((u) => /answers?|\/api\/web|\/api\/literature|followups/.test(u))).toBe(false);
  expect(urls.find((u) => u.includes('/v1/search?'))).toContain('q=MSC+knee+pain');
});

test('signed out, nothing found says so and offers sign-in to ask', async () => {
  serve({ claims: { items: [] }, posts: { topics: [], items: [] } });
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} />);
  search('zebrafish fin regrowth');
  const ask = await screen.findByRole('region', { name: 'Ask the network' });
  expect(ask).toHaveTextContent('Nothing here answers it yet.');
  expect(within(ask).getByText('Sign in to ask')).toHaveAttribute('href', '#/account');
  expect(screen.getByText('No claims match.')).toBeInTheDocument();
});

test('signed in, the search becomes a question for the network', async () => {
  localStorage.setItem('rrsrch_token', 'tok');
  const calls = serve();
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} />);
  search('Do MSCs help at 5 years?');
  const ask = await screen.findByRole('region', { name: 'Ask the network' });
  fireEvent.click(within(ask).getByRole('button', { name: 'Ask the network' }));
  expect(within(ask).getByLabelText('Question')).toHaveValue('Do MSCs help at 5 years?');
  fireEvent.change(within(ask).getByLabelText('Details'), { target: { value: 'I found 2-year data only.' } });
  fireEvent.click(within(ask).getByRole('button', { name: 'Post question' }));
  await screen.findByRole('region', { name: 'Ask the network' });
  await new Promise((r) => setTimeout(r, 0));
  const post = calls.find(([u, o]) => u === '/api/engine/v1/posts' && o.method === 'POST');
  expect(JSON.parse(post[1].body)).toEqual({ kind: 'question', title: 'Do MSCs help at 5 years?', body: 'I found 2-year data only.' });
  expect(window.location.pathname).toBe('/questions/41');
});
