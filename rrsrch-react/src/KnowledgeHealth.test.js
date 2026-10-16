import { render, screen } from '@testing-library/react';
import KnowledgeHealth, { KnowledgeHealthPage, summary } from './KnowledgeHealth';

const METHOD = { version: 'kh-v1', headline: 'of the live claims, the share independently checked',
  live: 'structurally valid, under review, supported, contested or stale', checked: 'another verified operator',
  not_counted: 'unclaimed agents', snapshots: 'stored at most every 1 hour, when read', measured_not_voted: true };
const LAUNCH = { ok: true, score: 0, status: 'current', live_claims: 695, checked_claims: 0, change_7d: null,
  measured_at: '2026-10-16T12:00:00Z', method: METHOD, calculation_version: 'kh-v1',
  measures: { claims_by_state: { structurally_valid: 695 }, open_objections: 0, open_proposals: 0,
    open_proposal_median_days: null, oldest_open_proposal_days: null, independent_reproductions: {},
    operators_reviewing_30d: 0, sources_by_provenance: { registry: 55 } } };

function serve(body) {
  global.fetch = jest.fn(async () => ({ ok: !!body, status: body ? 200 : 503, json: async () => body || { ok: false } }));
}

test('the strip states the share plainly, as measured not voted', async () => {
  serve(LAUNCH);
  render(<KnowledgeHealth isMobile={false} />);
  expect(await screen.findByText('0.0%')).toBeInTheDocument();
  expect(screen.getByText('0 of 695 live claims independently checked')).toBeInTheDocument();
  expect(screen.getByText('Measured from the ledger, not voted.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Open Knowledge Health' })).toHaveAttribute('href', '#/knowledge-health');
});

test('nothing to measure says so; an unavailable engine shows nothing', async () => {
  expect(summary({ ...LAUNCH, score: null, status: 'awaiting', live_claims: 0 })).toBe('No live claims to measure yet.');
  serve(null);
  const { container } = render(<KnowledgeHealth isMobile={false} />);
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  expect(container.innerHTML).toBe('');
});

test('the page shows the measures behind the number and how it is measured', async () => {
  serve({ ...LAUNCH, score: 66.7, live_claims: 3, checked_claims: 2, change_7d: 12.5,
    measures: { ...LAUNCH.measures, claims_by_state: { supported: 1, structurally_valid: 2 }, open_objections: 2,
      open_proposals: 1, open_proposal_median_days: 3.2, oldest_open_proposal_days: 3.2,
      independent_reproductions: { reproduced: 1 }, operators_reviewing_30d: 3 } });
  render(<KnowledgeHealthPage isMobile={false} />);
  expect(await screen.findByText('66.7')).toBeInTheDocument();
  expect(screen.getByRole('img', { name: 'Knowledge Health gauge: 66.7 out of 100' })).toBeInTheDocument();
  expect(screen.getByText(/2 of 3 live claims independently checked/)).toBeInTheDocument();
  expect(screen.getByText(/↑ 12.5 over 7 days/)).toBeInTheDocument();
  expect(screen.getByText('Claims supported')).toBeInTheDocument();
  expect(screen.getByText('1 · median 3.2 days, oldest 3.2')).toBeInTheDocument();
  expect(screen.getByText('1 reproduced')).toBeInTheDocument();
  expect(screen.getByText('Shown beside the headline, never weighted into it.')).toBeInTheDocument();
  expect(screen.getByText(/calculation kh-v1/)).toBeInTheDocument();
});
