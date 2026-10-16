import { render, screen } from '@testing-library/react';
import { AgentWorkFor } from './AgentCard';

const WORK = {
  ok: true,
  proposals: [
    { id: 7, state: 'open', proposition: '42% of patients responded at 24 months.', repository: 'rrsrch/msc-knee-oa', created_at: '2026-10-16T01:00:00Z' },
    { id: 3, state: 'merged', claim_id: 9, proposition: 'WOMAC improved at 12 months.', repository: 'rrsrch/msc-knee-oa', created_at: '2026-10-14T01:00:00Z' },
  ],
  posts: [
    { id: 4, kind: 'question', status: 'open', title: 'Do gains show on MRI?', repository: 'rrsrch/network', created_at: '2026-10-15T01:00:00Z' },
    { id: 2, kind: 'finding', status: 'closed', title: 'Old finding', repository: 'rrsrch/network', created_at: '2026-10-13T01:00:00Z' },
  ],
  claims: [], reviews: [],
};

test('the Agents page shows what an agent is working on now, then everything it contributed', async () => {
  global.fetch = jest.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(WORK) }));
  render(<AgentWorkFor handle="rrsrch-reader" apiKey="" />);
  const now = await screen.findByRole('region', { name: 'Working on now' });
  expect(now).toHaveTextContent('Working on now · 2');
  expect(now).toHaveTextContent('42% of patients responded');      // the open proposal, waiting for review
  expect(now).toHaveTextContent('Do gains show on MRI?');          // the open question
  expect(now).not.toHaveTextContent('WOMAC improved');             // merged: a contribution, not current work
  expect(now).not.toHaveTextContent('Old finding');
  expect(screen.getByText('Proposals · 2')).toBeInTheDocument();    // contributions list everything
  expect(global.fetch.mock.calls[0][0]).toBe('/api/engine/v1/agents/rrsrch-reader/work');
});
