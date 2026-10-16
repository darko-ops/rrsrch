import { render, screen, fireEvent } from '@testing-library/react';
import { TrialQueue } from './Dashboard';

const TEXT = 'Methods: 40 patients. Results: WOMAC improved more with MSCs (p = 0.01), while VAS did not differ.';
const S = TEXT.indexOf('WOMAC');
const E = TEXT.indexOf(', while');
const TRIALS = { ok: true, trials: 2, next_offset: null, items: [
  { source_id: 'MED:1', title: 'BM-MSC trial', year: 2019, waiting: 2 },
  { source_id: 'MED:2', title: 'Adipose trial', year: 2020, waiting: 1 }] };
const claim = (id, start, end, proposition) => ({ id, proposition, state: 'structurally_valid', type: 'empirical',
  contributor: 'rrsrch-reader', part: 'abstract', start, end, open_challenges: 0, reviews: [] });
const TRIAL = { ok: true, source_id: 'MED:1', title: 'BM-MSC trial', year: 2019,
  documents: [{ part: 'abstract', text: TEXT }],
  claims: [claim(7, S, E, 'WOMAC improved more with MSCs.'), claim(8, S, E, 'The WOMAC difference was significant.')] };

function mock() {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const body = url.includes('/trials/MED%3A1') ? TRIAL : url.includes('/trials/MED%3A2')
      ? { ...TRIAL, source_id: 'MED:2', title: 'Adipose trial', claims: [] }
      : url.includes('/trials') ? TRIALS : { ok: true, state: 'under_review', reasons: ['needs 1 more approval'] };
    return { ok: true, status: 200, json: async () => body };
  });
  return calls;
}

test('one abstract, every waiting claim marked and numbered, reviewed in place', async () => {
  const calls = mock();
  render(<TrialQueue apiKey="rrsrch_k" repo="rrsrch/msc-knee-oa" />);
  expect(await screen.findByText('2 claims waiting', { exact: false })).toBeInTheDocument();
  const marks = document.querySelectorAll('mark');
  expect(marks).toHaveLength(1);                                           // two claims, one shared span
  expect(marks[0].textContent).toBe('WOMAC improved more with MSCs (p = 0.01)');
  expect(document.querySelectorAll('sup')).toHaveLength(2);
  expect(screen.getByText('WOMAC improved more with MSCs.')).toBeInTheDocument();
  fireEvent.click(screen.getAllByText('Approve')[1]);
  expect(await screen.findByText('needs 1 more approval', { exact: false })).toBeInTheDocument();
  const rev = calls.find((c) => c.url === '/api/engine/v1/reviews');
  expect(JSON.parse(rev.opts.body)).toEqual({ target: 'claim:8', verdict: 'approve', findings: '' });
  fireEvent.click(screen.getByText('Next trial'));
  expect(await screen.findByText('Every claim on this trial has been reviewed.')).toBeInTheDocument();
});
