import { currentRoute, contentPath, goTo } from './routes';

afterEach(() => { window.history.replaceState(null, '', '/'); });

test('content lives at real paths', () => {
  window.history.replaceState(null, '', '/claims/3');
  expect(currentRoute()).toBe('claims/3');
  window.history.replaceState(null, '', '/agents/ada-lovelace');
  expect(currentRoute()).toBe('agents/ada-lovelace');
  window.history.replaceState(null, '', '/topics/knee-oa');
  expect(currentRoute()).toBe('topics/knee-oa');
  expect(contentPath('claims/abc')).toBeNull();
  expect(contentPath('agents/Bad_Handle')).toBeNull();
});

test('old hash links to content redirect to the real path', () => {
  window.history.replaceState(null, '', '/#/claims/3');
  expect(currentRoute()).toBe('claims/3');
  expect(window.location.pathname).toBe('/claims/3');
  expect(window.location.hash).toBe('');
  window.history.replaceState(null, '', '/#/agent/reader');
  expect(currentRoute()).toBe('agents/reader');
  expect(window.location.pathname).toBe('/agents/reader');
});

test('a hash route wins over a content path, and the path is dropped', () => {
  window.history.replaceState(null, '', '/claims/3#/explore');
  expect(currentRoute()).toBe('explore');
  expect(window.location.pathname).toBe('/');
  window.history.replaceState(null, '', '/claims/3#/');
  expect(currentRoute()).toBe('home');
});

test('goTo opens a path in the app', () => {
  const seen = [];
  const on = () => seen.push(window.location.pathname);
  window.addEventListener('popstate', on);
  goTo('/posts/9');
  window.removeEventListener('popstate', on);
  expect(seen).toEqual(['/posts/9']);
});
