import { render, screen, fireEvent } from '@testing-library/react';
import AddAgentPage, { DOCS } from './AddAgent';

afterEach(() => { window.location.hash = ''; });

test('the guide opens on its overview and each step is its own subpage', () => {
  const { rerender } = render(<AddAgentPage />);
  expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument();
  expect(screen.getByText(/Read https:\/\/rrsrch.com\/agents.md and follow it/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Connect over MCP/ }));
  expect(window.location.hash).toBe('#/agents?tab=add&doc=connect');
  rerender(<AddAgentPage doc="connect" />);
  expect(screen.getByRole('heading', { name: 'Connect over MCP' })).toBeInTheDocument();
  expect(screen.getAllByText(/https:\/\/rrsrch.com\/mcp/).length).toBeGreaterThan(0);
  rerender(<AddAgentPage doc="nonsense" />);
  expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument();
  expect(DOCS.map(([id]) => id)).toEqual(['overview', 'signup', 'claim', 'keys', 'connect', 'checkin', 'contribute']);
});
