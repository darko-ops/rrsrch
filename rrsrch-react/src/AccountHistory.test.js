import { render, screen, fireEvent } from '@testing-library/react';
import { TopBar } from './SearchExperience';
import { SearchHistoryPanel } from './AccountPages';
import { pushSearchHistory, readSearchHistory, SEARCH_EVENT } from './searchHistory';

beforeEach(() => localStorage.clear());

test('the header has an Account button where History was', () => {
  const onAccount = jest.fn();
  render(<TopBar isMobile={false} showSearch query="" onQueryChange={() => {}} onSearch={() => {}} onHome={() => {}}
    onAgents={() => {}} onAccount={onAccount} active="account" />);
  expect(screen.queryByText('History')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Account' }));
  expect(onAccount).toHaveBeenCalled();
});

test('Account lists this browser\'s searches, runs one again, and clears them', () => {
  pushSearchHistory('Do MSCs help knee OA?');
  pushSearchHistory('PRP for tennis elbow');
  const heard = [];
  const listen = (e) => heard.push(e.detail);
  window.addEventListener(SEARCH_EVENT, listen);
  render(<SearchHistoryPanel />);
  const items = screen.getAllByRole('button', { name: /\?|elbow/ });
  expect(items.map((b) => b.textContent)).toEqual(['PRP for tennis elbow', 'Do MSCs help knee OA?']);
  fireEvent.click(items[1]);
  expect(heard).toEqual(['Do MSCs help knee OA?']);
  fireEvent.click(screen.getByRole('button', { name: 'Clear history' }));
  expect(readSearchHistory()).toEqual([]);
  expect(screen.getByText(/No searches yet/)).toBeInTheDocument();
  window.removeEventListener(SEARCH_EVENT, listen);
});
