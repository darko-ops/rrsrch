import { render, screen } from '@testing-library/react';
import { VerifyEmail } from './App';

function mock(ok, body) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => { calls.push({ url, opts }); return { ok, json: async () => body }; });
  return calls;
}

test('the email link confirms the address with its token', async () => {
  window.location.hash = '#/verify?token=abc_123';
  const calls = mock(true, { ok: true });
  render(<VerifyEmail />);
  expect(await screen.findByText('Email confirmed.')).toBeInTheDocument();
  expect(calls[0].url).toBe('/api/account/verify');
  expect(JSON.parse(calls[0].opts.body)).toEqual({ token: 'abc_123' });
});

test('an expired link says so and points to the account page', async () => {
  window.location.hash = '#/verify?token=old';
  mock(false, { error: 'That link is invalid or has expired. Sign in and send a new one.' });
  render(<VerifyEmail />);
  expect(await screen.findByText(/has expired/)).toBeInTheDocument();
  expect(screen.getByText('Your account')).toBeInTheDocument();
});
