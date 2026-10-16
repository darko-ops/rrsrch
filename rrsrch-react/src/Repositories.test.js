import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Repositories } from './AccountPages';

function serve(items, sent) {
  global.fetch = jest.fn(async (url, opts = {}) => {
    if (opts.method === 'POST') { sent.push([url, JSON.parse(opts.body)]); return { ok: true, status: 201, json: async () => ({ ok: true }) }; }
    return { ok: true, status: 200, json: async () => ({ ok: true, items }) };
  });
}

test('an admin sees the organization\'s repositories and opens a new one with independent review', async () => {
  const sent = [];
  serve([{ slug: 'ominis-labs/finance', visibility: 'public', operator_verified: false, topic: 'SEC filings' },
    { slug: 'rrsrch/msc-knee-oa', visibility: 'public', operator_verified: true, topic: 'MSC' }], sent);
  render(<Repositories orgId="ominis-labs" token="t" admin verified={false} />);
  expect(await screen.findByText('ominis-labs/finance')).toBeInTheDocument();
  expect(screen.queryByText('rrsrch/msc-knee-oa')).not.toBeInTheDocument();           // only its own
  expect(screen.getByText('unverified operator')).toBeInTheDocument();
  expect(screen.getByText(/this will be an "unverified operator" repository/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Repository name'), { target: { value: 'Semis-Robotics' } });
  fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'Semiconductor capital intensity' } });
  fireEvent.click(screen.getByText('Create repository'));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toEqual(['/api/engine/v1/repos', { slug: 'ominis-labs/semis-robotics',
    topic: 'Semiconductor capital intensity', description: '', visibility: 'public',
    policy: { required_approvals: 1, approvals_from_other_orgs_only: true } }]);
});

test('members see the list but not the form', async () => {
  serve([], []);
  render(<Repositories orgId="lab" token="t" admin={false} verified />);
  expect(await screen.findByText('No repositories yet.')).toBeInTheDocument();
  expect(screen.queryByText('New repository')).not.toBeInTheDocument();
});
