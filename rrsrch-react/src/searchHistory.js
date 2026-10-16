/**
 * Search history: the questions this browser has asked, newest first, kept in this browser only (localStorage).
 * Its own module so the header, the home page and the Account page can share it without importing each other.
 */
const HISTORY_KEY = 'rrsrch_search_history';
export const SEARCH_EVENT = 'rrsrch:search';     // detail: the question; App opens the results and runs it

export function readSearchHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY) || sessionStorage.getItem(HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((x) => typeof x === 'string' && x.trim()) : [];
  } catch {
    return [];
  }
}

export function pushSearchHistory(q) {
  const next = [q, ...readSearchHistory().filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 30);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  return next;
}

export function clearSearchHistory() {
  try {
    localStorage.removeItem(HISTORY_KEY);
    sessionStorage.removeItem(HISTORY_KEY);
  } catch { /* ignore */ }
  return [];
}

// Ask the site to run a search from anywhere (the Account page's history, for one).
export function searchAgain(q) {
  window.dispatchEvent(new CustomEvent(SEARCH_EVENT, { detail: q }));
}
