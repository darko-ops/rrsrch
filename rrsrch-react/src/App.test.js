import { render, screen } from '@testing-library/react';
import App from './App';

// The 3D background needs WebGL and ResizeObserver, which jsdom doesn't have; the shell around it is what's tested.
jest.mock('@react-three/fiber', () => ({ Canvas: () => null, useFrame: () => {} }));
jest.mock('@react-three/drei', () => ({ OrbitControls: () => null, Sphere: () => null, Stars: () => null, Grid: () => null }));

beforeEach(() => {
  global.fetch = jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, items: [], topics: [] }) }));
  localStorage.clear();
});
afterEach(() => { window.location.hash = ''; });

test('the site shell renders with its navigation', () => {
  render(<App />);
  expect(screen.getAllByText(/^network$/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/agents/i).length).toBeGreaterThan(0);
});

test('hash routes open their pages', async () => {
  window.location.hash = '#/explore';
  render(<App />);
  expect(await screen.findByLabelText('Filter posts')).toBeInTheDocument();
});

test('on a post page, the Network links leave for the Network instead of being swallowed', async () => {
  window.history.pushState(null, '', '/questions/7');
  render(<App />);
  const link = document.createElement('a');                         // a "#/explore" link, like "← Network" and the header's
  link.setAttribute('href', '#/explore');
  document.body.appendChild(link);
  const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
  link.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(false);                       // the app lets the browser follow the hash
  const content = document.createElement('a');                      // a link to another post still opens in the app
  content.setAttribute('href', '/posts/9');
  document.body.appendChild(content);
  const event2 = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
  content.dispatchEvent(event2);
  expect(event2.defaultPrevented).toBe(true);
  expect(window.location.pathname).toBe('/posts/9');
  window.history.pushState(null, '', '/');
});
