import { render, act } from '@testing-library/react';
import { GoogleSignIn } from './App';

function mockFetch(clientId) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    if (url === '/api/account/config') return { ok: true, json: async () => ({ google_client_id: clientId }) };
    if (url === '/api/account/google') return { ok: true, json: async () => ({ token: 'tok.g', user: { id: 'u' } }) };
    return { ok: false, json: async () => ({}) };
  });
  return calls;
}
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

afterEach(() => { delete window.google; });

test('a Google credential is posted to the server and the account comes back', async () => {
  let opts;
  window.google = { accounts: { id: { initialize: (o) => { opts = o; }, renderButton: jest.fn() } } };
  const calls = mockFetch('cid.apps.googleusercontent.com');
  const signedIn = jest.fn();
  render(<GoogleSignIn onSignedIn={signedIn} onError={jest.fn()} />);
  await settle();
  expect(opts.client_id).toBe('cid.apps.googleusercontent.com');
  expect(window.google.accounts.id.renderButton).toHaveBeenCalled();
  await act(async () => { await opts.callback({ credential: 'id-token' }); });
  expect(JSON.parse(calls.find((c) => c.url === '/api/account/google').opts.body)).toEqual({ credential: 'id-token' });
  expect(signedIn).toHaveBeenCalledWith({ token: 'tok.g', user: { id: 'u' } });
});

test('without a configured client ID there is no Google button', async () => {
  mockFetch(null);
  const { container } = render(<GoogleSignIn onSignedIn={jest.fn()} onError={jest.fn()} />);
  await settle();
  expect(container.innerHTML).toBe('');
});
