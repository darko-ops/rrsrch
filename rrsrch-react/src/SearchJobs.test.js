import { render, screen, fireEvent, act } from '@testing-library/react';
import SearchExperience from './SearchExperience';

const ANSWER = {
  ok: true, engine: 'rrsrch', question: 'q', verdict: 'benefit', headline: 'Benefit: the claims favour MSCs.',
  kicker: 'Answer from 1 finding in 1 study', sentences: [{ text: 'Pain was lower with MSCs.', cites: ['5'] }],
  citations: { 5: { text: 'Pain was lower (p = 0.01).', src: 'Trial', verdict: 'benefit', url: null } },
  groups: [], gaps: null, engineLive: true,
};

function json(status, body) {
  return { ok: status < 400, status, json: async () => body };
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

async function ask(text) {
  fireEvent.change(screen.getByPlaceholderText(/Ask a question/), { target: { value: text } });
  fireEvent.submit(screen.getByPlaceholderText(/Ask a question/).closest('form'));
}

test('an answer is started, its stage shown while waiting, then rendered when done', async () => {
  let polls = 0;
  global.fetch = jest.fn(async (url, opts = {}) => {
    if (url === '/api/engine/v1/answers' && opts.method === 'POST') {
      return json(202, { ok: true, job_id: 'j1', status: 'running', stage: 'finding claims and writing the answer' });
    }
    if (url === '/api/engine/v1/answers/j1') {
      polls += 1;
      return polls < 2 ? json(200, { ok: true, job_id: 'j1', status: 'running', stage: 'packaging the answer' })
        : json(200, { ok: true, job_id: 'j1', status: 'done', answer: ANSWER });
    }
    return json(200, { results: [], suggestions: [] });
  });
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} onAgents={() => {}} />);
  await act(async () => { await ask('Does MSC reduce pain?'); });
  expect(await screen.findByText(/writing a cited answer/)).toBeInTheDocument();
  expect(screen.getByText(/finding claims and writing the answer/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Search/ })).not.toBeDisabled();          // free to ask something else
  await act(async () => { jest.advanceTimersByTime(3100); });
  expect(await screen.findByText(/packaging the answer/)).toBeInTheDocument();
  await act(async () => { jest.advanceTimersByTime(3100); });
  expect(await screen.findByText('the claims favour MSCs.')).toBeInTheDocument();
  expect(screen.queryByText(/writing a cited answer/)).not.toBeInTheDocument();
});

test('an engine without jobs falls back to the one-shot answer', async () => {
  global.fetch = jest.fn(async (url) => {
    if (url === '/api/engine/v1/answers') return json(404, { ok: false, error: 'not found' });
    if (url === '/api/engine/answer') return json(200, ANSWER);
    return json(200, { results: [], suggestions: [] });
  });
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} onAgents={() => {}} />);
  await act(async () => { await ask('Does MSC reduce pain?'); });
  expect(await screen.findByText('the claims favour MSCs.')).toBeInTheDocument();
});

test('a failed job says so instead of hanging', async () => {
  global.fetch = jest.fn(async (url, opts = {}) => {
    if (url === '/api/engine/v1/answers' && opts.method === 'POST') return json(202, { ok: true, job_id: 'j2', status: 'queued', stage: 'waiting to start' });
    if (url === '/api/engine/v1/answers/j2') return json(200, { ok: true, job_id: 'j2', status: 'failed', error: 'model timed out' });
    return json(200, { results: [], suggestions: [] });
  });
  render(<SearchExperience isMobile={false} scrollContainerRef={{ current: null }} onAgents={() => {}} />);
  await act(async () => { await ask('Does MSC reduce pain?'); });
  expect(await screen.findByText(/Waiting for the engine/)).toBeInTheDocument();
  await act(async () => { jest.advanceTimersByTime(3100); });
  expect(await screen.findByText(/could not answer this time/)).toBeInTheDocument();
  expect(screen.getByText('model timed out')).toBeInTheDocument();
});
