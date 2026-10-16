import { render, screen } from '@testing-library/react';
import SourceLine, { sourceHref } from './SourceLine';

test('a fetched source links to where it came from; a paper to PubMed', () => {
  expect(sourceHref({ source_id: 'SEC:0000320193-24-000123:aapl-20240928.htm',
    source_url: 'https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm' }))
    .toMatch(/^https:\/\/www\.sec\.gov\//);
  expect(sourceHref({ source_id: 'MED:123' })).toBe('https://pubmed.ncbi.nlm.nih.gov/123/');
  expect(sourceHref({ source_id: 'UP:abc', source_provenance: 'uploaded' })).toBeNull();
  render(<SourceLine ev={{ source_id: 'URL:ab12', source_title: 'Award notice', source_provenance: 'fetched',
    source_url: 'https://example.gov/award' }} prefix="supports" />);
  expect(screen.getByRole('link', { name: /Award notice/ })).toHaveAttribute('href', 'https://example.gov/award');
  expect(screen.queryByText('agent-supplied')).not.toBeInTheDocument();
});

test('an upload is marked agent-supplied, with its origin', () => {
  render(<SourceLine ev={{ source_id: 'UP:9f', source_title: 'Private report', source_provenance: 'uploaded',
    source_origin: 'Board deck shared by the company, Oct 2026' }} />);
  expect(screen.getByText('agent-supplied')).toBeInTheDocument();
  expect(screen.getByText(/Board deck shared/)).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});
