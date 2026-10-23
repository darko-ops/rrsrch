/**
 * Signing out of the whole app: the server ends every sign-in token this account's browsers hold, then this browser
 * forgets everything that identifies the visitor (the sign-in, a connected agent key, a pending claim, the search
 * history) and reloads at the home page, so no page keeps acting as them.
 */
export const SIGNED_IN_STORAGE = ['rrsrch_token', 'rrsrch_engine_key', 'rrsrch_pending_claim', 'rrsrch_user',
  'rrsrch_user_profile', 'rrsrch_search_history'];

export function forgetThisBrowser() {
  for (const k of SIGNED_IN_STORAGE) {
    try { localStorage.removeItem(k); } catch { /* storage blocked */ }
    try { sessionStorage.removeItem(k); } catch { /* storage blocked */ }
  }
}

export async function signOut({ reload = () => window.location.replace('/') } = {}) {
  let token = '';
  try { token = localStorage.getItem('rrsrch_token') || ''; } catch { /* none */ }
  if (token) {
    try {
      await fetch('/api/account/signout', { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
    } catch { /* offline: this browser still forgets it */ }
  }
  forgetThisBrowser();
  reload();
}
