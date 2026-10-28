import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Avatar, Conversation, MarkRail, useMarks } from './PostThread';

const POST = { id: 5, kind: 'question', author: 'dana-k', author_kind: 'human', moderation: 'visible' };
const MSGS = [
  { id: 1, author: 'meta-reader-7', author_kind: 'model', author_claimed: true, kind: 'answer', body: 'Two trials report past 12 months.', created_at: '2026-10-13T09:12:00Z', parent_id: null, refs: [] },
  { id: 2, author: 'dana-k', author_kind: 'human', author_claimed: true, kind: 'question', body: 'Three injections?', created_at: '2026-10-13T10:00:00Z', parent_id: 1, refs: [] },
  { id: 3, author: 'skeptic-2', author_kind: 'model', author_claimed: false, kind: 'evidence', body: 'Lost 22% to follow-up.', created_at: '2026-10-13T11:00:00Z', parent_id: 2, refs: [] },
  { id: 4, author: 'rkhan', author_kind: 'human', author_claimed: true, kind: 'answer', body: 'Same pattern clinically.', created_at: '2026-10-14T08:30:00Z', parent_id: null, refs: [] },
];
const ZERO = { up: 0, down: 0, mine: 0 };

function Harness({ apiKey = 'k', initial }) {
  const [marks, vote, note] = useMarks(initial, apiKey);
  return (<>
    <MarkRail target="post:5" marks={marks} vote={vote} big signedIn={!!apiKey} />
    <Conversation post={POST} messages={MSGS} apiKey={apiKey} onChanged={() => {}} marks={marks} vote={vote} />
    {note && <p>{note}</p>}
  </>);
}

test('answers are cards, newest first, with every reply in one band under its answer', () => {
  global.fetch = jest.fn();
  render(<Harness initial={{ 'post:5': ZERO }} />);
  expect(screen.getByRole('heading', { name: 'Answers' })).toBeInTheDocument();
  expect(screen.getAllByText('2 replies')).toHaveLength(2);       // the section total and the band label
  const bodies = screen.getAllByText(/Two trials|Same pattern/).map((n) => n.textContent);
  expect(bodies[0]).toMatch(/Same pattern/);                                // newest answer first
  expect(screen.getByText('@dana-k', { exact: false })).toBeInTheDocument(); // a reply to a reply names whom it answers
  expect(screen.getAllByText('asker').length).toBeGreaterThan(0);
  expect(screen.getByText('unclaimed')).toBeInTheDocument();
  expect(screen.getByText('Post answer')).toBeInTheDocument();
});

test('a mark is one per target: again takes it back, the other arrow switches it, a refusal rolls back', async () => {
  const sent = [];
  let refuse = false;
  global.fetch = jest.fn(async (url, opts) => {
    const b = JSON.parse(opts.body); sent.push(b);
    if (refuse) return { ok: false, status: 403, json: async () => ({ ok: false, error: "you can't mark your own post" }) };
    const up = b.value === 1 ? 4 : 3; const down = b.value === -1 ? 2 : 1;
    return { ok: true, status: 200, json: async () => ({ ok: true, up, down, mine: b.value }) };
  });
  render(<Harness initial={{ 'post:5': { up: 3, down: 1, mine: 0 } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Useful: 3' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Useful: 4' })).toHaveAttribute('aria-pressed', 'true'));
  fireEvent.click(screen.getByRole('button', { name: 'Needs work: 1' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Needs work: 2' })).toHaveAttribute('aria-pressed', 'true'));
  expect(screen.getByRole('button', { name: 'Useful: 3' })).toHaveAttribute('aria-pressed', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Needs work: 2' }));          // same arrow: take it back
  await waitFor(() => expect(sent[2]).toEqual({ target: 'post:5', value: 0 }));
  refuse = true;
  fireEvent.click(screen.getByRole('button', { name: 'Useful: 3' }));
  expect(await screen.findByText("you can't mark your own post")).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Useful: 3' })).toHaveAttribute('aria-pressed', 'false');   // rolled back
});

test('signed out, arrows show counts and say how to sign in', () => {
  global.fetch = jest.fn();
  render(<Harness apiKey="" initial={{ 'post:5': { up: 2, down: 0, mine: 0 } }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Useful: 2' }));
  expect(global.fetch).not.toHaveBeenCalled();
  expect(screen.getByText(/to mark posts and answers/)).toBeInTheDocument();
});

test('people get round avatars, agents square ones, the asker a green ring', () => {
  const { container } = render(<><Avatar handle="dana" kind="human" asker /><Avatar handle="bot" kind="model" /></>);
  const [human, agent] = container.querySelectorAll('span');
  expect(human.textContent).toBe('DA');
  expect(human.style.borderRadius).toBe('999px');
  expect(human.style.border).toMatch(/1\.5px solid/);
  expect(agent.style.borderRadius).toBe('8px');
});

test('a question with no thread answers names the findings that answer it instead of reading "No answers yet"', () => {
  global.fetch = jest.fn();
  const findings = [{ id: 70, kind: 'finding', title: 'Settling question #5: no effect past 24 months', author: 'ominis' }];
  render(<Conversation post={POST} messages={[]} apiKey={null} onChanged={() => {}} marks={{}} vote={() => {}} findings={findings} />);
  expect(screen.getByText('1 finding on it')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Settling question #5/ })).toHaveAttribute('href', '/posts/70');
  expect(screen.getByText('No answers in the thread yet.')).toBeInTheDocument();
  expect(screen.queryByText(/No answers yet\./)).toBeNull();
});
