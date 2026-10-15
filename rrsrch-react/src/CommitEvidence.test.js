import { render, screen } from '@testing-library/react';
import CommitEvidence, { commitLinks, isCommit } from './CommitEvidence';

const SHA = '0123456789abcdef0123456789abcdef01234567';
const EV = { id: 1, relation: 'supports', kind: 'git_ref', source_id: null,
  git: { repo_url: 'https://github.com/o/r', commit: SHA, tag: 'v1.2.3', path: 'src/a.py', start_line: 3, end_line: 9 } };

test('a commit is shown with links to the commit, the lines at that commit, and the tag', () => {
  render(<CommitEvidence ev={EV} mono="monospace" />);
  expect(screen.getByText(SHA.slice(0, 12)).getAttribute('href')).toBe(`https://github.com/o/r/commit/${SHA}`);
  expect(screen.getByText('src/a.py lines 3–9').getAttribute('href')).toBe(`https://github.com/o/r/blob/${SHA}/src/a.py#L3-L9`);
  expect(screen.getByText('v1.2.3').getAttribute('href')).toBe('https://github.com/o/r/tree/v1.2.3');
  expect(screen.queryByText(/null/)).toBeNull();
});

test('each forge gets its own link spelling, and unknown hosts get no links', () => {
  expect(commitLinks({ repo_url: 'https://gitlab.com/o/r', commit: SHA }).commit).toBe(`https://gitlab.com/o/r/-/commit/${SHA}`);
  expect(commitLinks({ repo_url: 'https://codeberg.org/o/r', commit: SHA, path: 'a.py', start_line: 1, end_line: 2 }).file)
    .toBe(`https://codeberg.org/o/r/src/commit/${SHA}/a.py#L1-L2`);
  expect(commitLinks({ repo_url: 'https://example.com/o/r', commit: SHA })).toBeNull();
  expect(isCommit({ kind: 'document_span' })).toBeFalsy();
});
