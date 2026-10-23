import { signOut, SIGNED_IN_STORAGE } from './signOut';

test('signing out ends the account on the server and this browser forgets every way it acted as them', async () => {
  for (const k of SIGNED_IN_STORAGE) localStorage.setItem(k, 'x');
  localStorage.setItem('rrsrch_token', 'tok.9');
  localStorage.setItem('rrsrch_dashboard_tab', 'account');        // a view preference, kept
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ ok: true }) }));
  const reload = jest.fn();
  await signOut({ reload });
  expect(global.fetch).toHaveBeenCalledWith('/api/account/signout',
    { method: 'POST', headers: { Authorization: 'Bearer tok.9' } });
  for (const k of SIGNED_IN_STORAGE) expect(localStorage.getItem(k)).toBeNull();
  expect(localStorage.getItem('rrsrch_dashboard_tab')).toBe('account');
  expect(reload).toHaveBeenCalled();
});

test('offline, or with only an agent key, this browser still forgets it all', async () => {
  localStorage.setItem('rrsrch_engine_key', 'tok.8');
  global.fetch = jest.fn(async () => { throw new Error('offline'); });
  const reload = jest.fn();
  await signOut({ reload });
  expect(global.fetch).not.toHaveBeenCalled();                     // no sign-in to end on the server
  expect(localStorage.getItem('rrsrch_engine_key')).toBeNull();
  expect(reload).toHaveBeenCalled();
});
