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
  expect(screen.getAllByText(/explore/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/agents/i).length).toBeGreaterThan(0);
});

test('hash routes open their pages', async () => {
  window.location.hash = '#/explore';
  render(<App />);
  expect(await screen.findByLabelText('Filter posts')).toBeInTheDocument();
});
