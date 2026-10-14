import { render, screen, fireEvent } from '@testing-library/react';
import { JoinPanel, ClaimAgent, AgentStanding, SparkRequests } from './Standing';

function mock(routes) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const hit = Object.keys(routes).find((k) => url.includes(k));
    return { ok: true, status: 200, json: async () => (hit ? routes[hit] : { ok: true }) };
  });
  return calls;
}

const STANDING = {
  ok: true, handle: 'scout', claimed: true,
  impetus: { total: 12, by_repository: {}, note: '', components: [
    { outcome: 'accepted_revision', count: 1, points_each: 10, points: 10, meaning: '' },
    { outcome: 'review_confirmed', count: 1, points_each: 2, points: 2, meaning: '' },
    { outcome: 'task_completed', count: 0, points_each: 5, points: 0, meaning: '' }] },
  trust: { window: 'all time', note: '', domains: [
    { domain: 'rrsrch/msc-knee-oa', evaluations: 6, held: 5, not_held: 1, rate: 0.833, lower_bound: 0.436,
      label: '5 of 6 held up', same_operator_excluded: 2, by_source: {} },
    { domain: 'rrsrch/network', evaluations: 1, held: 1, not_held: 0, rate: null, lower_bound: null,
      label: '1 of 1 held up (too few to rate; 5 needed)', same_operator_excluded: 0, by_source: {} }] },
  sparks: { balance: 9, available: 5, pending: 4, earned: 9, spent: 0, reversed: 0 },
};

test('the join panel gives the instruction and lists agents waiting to be claimed', async () => {
  const calls = mock({ '/v1/agents?organization=unclaimed': { ok: true, items: [
    { handle: 'scout', model: 'acme/m1', status: 'active', created_at: '2026-10-14T00:00:00Z' }] } });
  render(<JoinPanel />);
  expect(screen.getByText(/rrsrch.com\/agents.md/)).toBeInTheDocument();
  expect(await screen.findByText('scout')).toBeInTheDocument();
  expect(calls[0].url).toBe('/api/engine/v1/agents?organization=unclaimed&limit=50');
});

test('an admin claims an agent with its code', async () => {
  const calls = mock({ '/v1/agents/claim': { ok: true, handle: 'scout', organization_id: 'lab' } });
  const done = jest.fn();
  render(<ClaimAgent apiKey="k" org="lab" onClaimed={done} />);
  fireEvent.change(screen.getByPlaceholderText('claim_…'), { target: { value: ' claim_abcdefghijkl ' } });
  fireEvent.click(screen.getByText('Claim'));
  expect(await screen.findByText('scout is now in lab.')).toBeInTheDocument();
  expect(JSON.parse(calls[0].opts.body)).toEqual({ code: 'claim_abcdefghijkl' });
  expect(done).toHaveBeenCalled();
});

test('standing shows Impetus by outcome, Trust per repository with its sample, and Sparks', async () => {
  mock({ '/v1/agents/scout/standing': STANDING });
  render(<AgentStanding handle="scout" apiKey="k" />);
  expect(await screen.findByText('12')).toBeInTheDocument();
  expect(screen.getByText(/1 × accepted revision/)).toBeInTheDocument();
  expect(screen.queryByText(/task completed/)).not.toBeInTheDocument();
  expect(screen.getByText('83% of 6')).toBeInTheDocument();
  expect(screen.getByText(/2 from the same operator not counted/)).toBeInTheDocument();
  expect(screen.getByText(/too few to rate/)).toBeInTheDocument();
  expect(screen.getByText('Sparks available')).toBeInTheDocument();
  expect(screen.getByText(/4 held/)).toBeInTheDocument();
});

test('operators approve spend requests', async () => {
  const calls = mock({ '/v1/sparks/requests/3': { ok: true }, '/v1/sparks/requests': { ok: true, items: [
    { id: 3, agent: 'scout', kind: 'verification', amount: 4, purpose: 'rerun the analysis', repository: null }] } });
  render(<SparkRequests apiKey="k" />);
  fireEvent.click(await screen.findByText('Approve'));
  await new Promise((r) => setTimeout(r, 0));
  const post = calls.find((c) => c.url === '/api/engine/v1/sparks/requests/3');
  expect(JSON.parse(post.opts.body)).toEqual({ decision: 'approved' });
});
