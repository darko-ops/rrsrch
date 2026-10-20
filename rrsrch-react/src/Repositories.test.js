import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Repositories } from './AccountPages';
import { resetTopics } from './topicTree';

const TOPICS = [{ slug: 'technology', title: 'Technology', parent: null, description: '', total: {} },
  { slug: 'semiconductors', title: 'Semiconductors', parent: 'technology', description: '', total: {} }];
beforeEach(() => resetTopics());

function serve(items, sent) {
  global.fetch = jest.fn(async (url, opts = {}) => {
    if (url.includes('/v1/topics')) return { ok: true, status: 200, json: async () => ({ ok: true, items: TOPICS }) };
    if (opts.method === 'POST') { sent.push([url, JSON.parse(opts.body)]); return { ok: true, status: 201, json: async () => ({ ok: true }) }; }
    return { ok: true, status: 200, json: async () => ({ ok: true, items }) };
  });
}

test('an admin sees the organization\'s collections and opens a new one, filed in the tree, with independent review', async () => {
  const sent = [];
  serve([{ slug: 'ominis-labs/finance', visibility: 'public', operator_verified: false, topic: 'SEC filings' },
    { slug: 'rrsrch/msc-knee-oa', visibility: 'public', operator_verified: true, topic: 'MSC' }], sent);
  render(<Repositories orgId="ominis-labs" token="t" admin verified={false} />);
  expect(await screen.findByText('ominis-labs/finance')).toBeInTheDocument();
  expect(screen.queryByText('rrsrch/msc-knee-oa')).not.toBeInTheDocument();           // only its own
  expect(screen.getByText('unverified operator')).toBeInTheDocument();
  expect(screen.getByText(/this will be an "unverified operator" collection/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Collection name'), { target: { value: 'Semis-Robotics' } });
  fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Semiconductor capital intensity' } });
  fireEvent.change(screen.getByLabelText('Add a topic'), { target: { value: 'semi' } });
  fireEvent.mouseDown(await screen.findByRole('option', { name: /Semiconductors · Technology/ }));
  expect(screen.queryByLabelText('Add a topic')).not.toBeInTheDocument();             // one place in the tree
  fireEvent.click(screen.getByText('Create collection'));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toEqual(['/api/engine/v1/repos', { slug: 'ominis-labs/semis-robotics',
    topic: 'Semiconductor capital intensity', description: '', topic_slug: 'semiconductors', visibility: 'public',
    policy: { required_approvals: 1, approvals_from_other_orgs_only: true } }]);
});

test('an admin deletes a collection by typing its full name', async () => {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push([url, opts.method || 'GET']);
    if (url.includes('/v1/topics')) return { ok: true, status: 200, json: async () => ({ ok: true, items: TOPICS }) };
    return { ok: true, status: 200, json: async () => ({ ok: true, items: [{ slug: 'ominis-labs/old', visibility: 'private', topic: 'Old' }] }) };
  });
  render(<Repositories orgId="ominis-labs" token="t" admin verified />);
  fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
  const sure = screen.getByRole('button', { name: 'Delete it' });
  expect(sure).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Confirm deleting ominis-labs/old'), { target: { value: 'ominis-labs/old' } });
  fireEvent.click(sure);
  await waitFor(() => expect(calls.some(([u, m]) => m === 'DELETE')).toBe(true));
  expect(calls.find(([, m]) => m === 'DELETE')[0]).toBe('/api/engine/v1/repos/ominis-labs/old?confirm=ominis-labs%2Fold');
});

test('members see the list but not the form or Delete', async () => {
  serve([{ slug: 'lab/notes', visibility: 'private', topic: 'Notes' }], []);
  render(<Repositories orgId="lab" token="t" admin={false} verified />);
  expect(await screen.findByText('lab/notes')).toBeInTheDocument();
  expect(screen.queryByText('New collection')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
});
