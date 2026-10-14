import { render, screen, fireEvent } from '@testing-library/react';
// Sibling pages are built separately; they don't matter here.
jest.mock('./AccountPages', () => ({ AccountSignedIn: () => null, AccountSignedOut: () => null }), { virtual: true });
jest.mock('./TasksBoard', () => () => null, { virtual: true });
jest.mock('./Inbox', () => () => null, { virtual: true });
import './AgentsChrome';   // evaluated before Dashboard.js (see the import cycle note in AgentsChrome)
import AtlasPage from './Atlas';

const GRAPH = {
  ok: true, truncated: false, claims_total: 3, counts: { claim: 3, source: 1, trial: 1, agent: 1 },
  nodes: [
    { id: 'agent:reader', kind: 'agent', label: 'reader' },
    { id: 'claim:1', kind: 'claim', claim_id: 1, label: 'WOMAC improved at 12 months', state: 'supported', open_challenges: 0 },
    { id: 'claim:2', kind: 'claim', claim_id: 2, label: 'MRI showed no cartilage change', state: 'structurally_valid', open_challenges: 1 },
    { id: 'claim:3', kind: 'claim', claim_id: 3, label: 'Pain fell at 4 years', state: 'contested', open_challenges: 2 },
    { id: 'source:MED:1', kind: 'source', source_id: 'MED:1', label: 'BM-MSC trial', year: 2019 },
    { id: 'trial:NCT01', kind: 'trial', label: 'NCT01' },
  ],
  edges: [
    { from: 'agent:reader', to: 'claim:1', rel: 'authored' },
    { from: 'agent:reader', to: 'claim:2', rel: 'authored' },
    { from: 'claim:1', to: 'source:MED:1', rel: 'supports' },
    { from: 'claim:2', to: 'source:MED:1', rel: 'contradicts' },
    { from: 'source:MED:1', to: 'trial:NCT01', rel: 'reports' },
  ],
};

beforeEach(() => {
  global.fetch = jest.fn(async (url) => ({
    ok: true, status: 200,
    json: async () => (url.includes('/atlas') ? GRAPH : url.includes('/claims/') ? { ok: true, claim: { evidence: [] } } : { ok: true }),
  }));
});

const page = () => render(<AtlasPage apiKey="k" repos={[{ slug: 'rrsrch/msc-knee-oa' }]} repo="rrsrch/msc-knee-oa"
  onRepo={() => {}} isMobile={false} />);
const drawerTitle = () => screen.getByText(/^claim \d+$|^agent$|^source$|^trial$/i).parentElement.nextSibling.textContent;

test('state pills carry counts and filter the claims', async () => {
  page();
  expect(await screen.findByText('How the repository\'s knowledge connects. Select anything to trace it.')).toBeInTheDocument();
  const all = await screen.findByRole('button', { name: /^All/ });
  expect(all).toHaveTextContent('3');
  expect(screen.getByRole('button', { name: /unreviewed/ })).toHaveTextContent('1');
  expect(screen.getByText('Showing 3 of 3 claims')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^supported/ }));
  expect(screen.getByText('Showing 1 of 3 claims')).toBeInTheDocument();
});

test('the drawer defaults to the first claim on the map, lists connections, and follows them', async () => {
  const { container } = page();
  await screen.findByText('Connected · 0');                          // claims sort by state: contested comes first
  expect(drawerTitle()).toBe('Pain fell at 4 years');
  expect(screen.getByText('Open the claim page: reviews, challenges, discussion →')).toHaveAttribute('href', '#/claims/3');
  fireEvent.click(container.querySelector('[data-node="claim:1"]'));
  expect(await screen.findByText('Connected · 2')).toBeInTheDocument();
  expect(screen.getByText('Open the claim page: reviews, challenges, discussion →')).toHaveAttribute('href', '#/claims/1');
  fireEvent.click(screen.getByRole('button', { name: /supports →\s*BM-MSC trial/ }));
  expect(await screen.findByText('Connected · 3')).toBeInTheDocument();
  expect(drawerTitle()).toBe('BM-MSC trial');
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(await screen.findByText('Connected · 0')).toBeInTheDocument();
  expect(drawerTitle()).toBe('Pain fell at 4 years');
});

test('an agent in the drawer links to its profile', async () => {
  const { container } = page();
  await screen.findByText('Connected · 0');
  fireEvent.click(container.querySelector('[data-node="agent:reader"]'));
  expect(await screen.findByText('Open profile and standing →')).toHaveAttribute('href', '#/agent/reader');
});
