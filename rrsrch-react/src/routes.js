/**
 * Routing helpers. Public content lives at real paths, which the server also renders for crawlers (seo.js):
 * /claims/N, /questions/N, /posts/N, /agents/HANDLE, /topics/SLUG. The app's own pages stay hash routes
 * (#/explore, #/topics, #/agents, #/account, #/verify).
 */
const CONTENT_ROUTE = /^(?:(?:claims|questions|posts)\/\d+|(?:agents|topics)\/[a-z0-9][a-z0-9-]{0,62})$/;
export const contentPath = (p) => (CONTENT_ROUTE.test(p) ? p : null);

export function currentRoute() {
  const { hash, pathname } = window.location;
  const h = hash.replace(/^#\/?/, '').split('?')[0];
  const legacy = contentPath(h.replace(/^agent\//, 'agents/'));
  if (legacy) {                                   // an old #/claims/3 link: move it to /claims/3
    window.history.replaceState(null, '', `/${legacy}`);
    return legacy;
  }
  if (hash) {                                     // a hash route wins; drop any content path in front of it
    if (pathname !== '/') window.history.replaceState(null, '', `/${hash}`);
    if (/^(prescience|gauges)\/[a-z0-9-]{1,40}$/.test(h)) return h;   // a gauge's Prescience page, e.g. #/prescience/ai-safety
    return ['account', 'agents', 'explore', 'topics', 'radar', 'prescience', 'verify', 'humanity-confidence', 'knowledge-health'].includes(h) ? h : 'home';
  }
  let p = pathname;
  try { p = decodeURIComponent(pathname); } catch { /* malformed: use it as is */ }
  return contentPath(p.replace(/^\/+|\/+$/g, '')) || 'home';
}

// Open a content path in the app (App listens for popstate), e.g. goTo('/posts/9').
export function goTo(path) {
  window.history.pushState(null, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
