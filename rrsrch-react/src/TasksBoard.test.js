// sibling Agents pages aren't under test; mocked so this suite doesn't depend on how they load
jest.mock('./AccountPages', () => ({ AccountSignedIn: () => null, AccountSignedOut: () => null }));
jest.mock('./Atlas', () => () => null);
import { render, screen, fireEvent, within } from '@testing-library/react';
import TasksBoard, { budgetOf } from './TasksBoard';

const TASKS = { ok: true, items: [
  { id: 1, question: 'Were MRI readers blinded?', deliverable: 'A table of blinding', state: 'authorized',
    created_by: 'demetri', assignee: null, budget: { sparks: 50 }, due_at: null },
  { id: 2, question: 'Pool the 12-month WOMAC', deliverable: 'A forest plot', state: 'in_progress',
    created_by: 'demetri', assignee: 'scout', budget: 20, due_at: new Date(Date.now() + 86400000).toISOString() },
  { id: 3, question: 'Check dosing units', deliverable: 'A note', state: 'proposed', created_by: 'ext', assignee: null,
    budget: {}, due_at: null },
  { id: 4, question: 'Old failed task', deliverable: 'x', state: 'failed', created_by: 'ext', assignee: null, budget: {} },
] };

function mock() {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    if (url.includes('/transition')) return { ok: true, status: 200, json: async () => ({ ok: true }) };
    if (url.includes('/tasks?')) return { ok: true, status: 200, json: async () => TASKS };
    return { ok: true, status: 200, json: async () => ({ ok: true, items: [] }) };
  });
  return calls;
}
const me = { handle: 'scout' };
const props = { apiKey: 'k', me, repos: [{ slug: 'rrsrch/msc-knee-oa' }], repo: 'rrsrch/msc-knee-oa', onRepo: () => {} };

test('six columns hold their tasks, with budget, due date and who has it', async () => {
  mock();
  render(<TasksBoard {...props} isMobile={false} />);
  await screen.findByText('Were MRI readers blinded?');
  const col = (name) => within(screen.getByRole('region', { name }));
  expect(col('Authorized').getByText('Were MRI readers blinded?')).toBeInTheDocument();
  expect(col('Authorized').getByText('50 ✦')).toBeInTheDocument();
  expect(col('In progress').getByText('you')).toBeInTheDocument();
  expect(col('In progress').getByText(/due (in 1 d|today)/)).toBeInTheDocument();
  expect(col('Proposed').getByText('by ext')).toBeInTheDocument();
  expect(screen.queryByText('Old failed task')).not.toBeInTheDocument();
  expect(budgetOf(7)).toBe(7);
  expect(budgetOf({})).toBe(null);
});

test('filters: assigned to me, up for grabs, archive', async () => {
  mock();
  render(<TasksBoard {...props} isMobile={false} />);
  await screen.findByText('Were MRI readers blinded?');
  fireEvent.click(screen.getByText('Assigned to me'));
  expect(screen.queryByText('Were MRI readers blinded?')).not.toBeInTheDocument();
  expect(screen.getByText('Pool the 12-month WOMAC')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Up for grabs'));
  expect(screen.getByText('Were MRI readers blinded?')).toBeInTheDocument();
  expect(screen.queryByText('Pool the 12-month WOMAC')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Archive'));
  expect(screen.getByText('Old failed task')).toBeInTheDocument();
});

test('Take it assigns an authorized task to you', async () => {
  const calls = mock();
  render(<TasksBoard {...props} isMobile={false} />);
  fireEvent.click(await screen.findByText('Take it'));
  await new Promise((r) => setTimeout(r, 0));
  const t = calls.find((c) => c.url === '/api/engine/v1/tasks/1/transition');
  expect(JSON.parse(t.opts.body)).toEqual({ to: 'assigned' });
});

test('List shows today\'s list view', async () => {
  mock();
  render(<TasksBoard {...props} isMobile={false} />);
  await screen.findByText('Were MRI readers blinded?');
  fireEvent.click(screen.getByRole('button', { name: 'List' }));
  expect(await screen.findByText('Research tasks')).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Authorized' })).not.toBeInTheDocument();
});
