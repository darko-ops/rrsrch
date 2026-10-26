import { render, screen, within } from '@testing-library/react';
import { MissionChips, MissionPage, MissionsIndex, Report, TopicMissions } from './Missions';
import { currentRoute } from './routes';

const COUNTS = { questions: 3, questions_open: 2, findings: 1, claims: 1, contributors: 4, open_bounties: 1 };
const SUMMARY = { id: 1, title: 'Do senolytic therapies produce reproducible health benefits in mammals?',
  objective: 'Evaluate controlled studies and whether benefits replicate.', status: 'active', featured: true,
  topic: 'medicine', topic_title: 'Medicine', deliverable: 'Evidence synthesis v1', counts: COUNTS };
const BOUNTY = { id: 4, state: 'open', amount: 22, held: 20, deadline: new Date(Date.now() + 6 * 864e5).toISOString() };
const MISSION = {
  mission: { ...SUMMARY, scope: '2018-2026; controlled studies', proposed_by: 'lab-bot',
    success_criteria: ['A documented literature search', 'An independently reviewed report'],
    report: '## Methods\nSearched PubMed.', report_label: 'Preliminary: not independently verified' },
  questions: [
    { id: 12, kind: 'question', title: 'Which controlled mammalian studies exist?', status: 'open', author: 'ominis',
      replies: 0, spark_bounty: BOUNTY },
    { id: 13, kind: 'question', title: 'Which benefits replicate?', status: 'answered', author: 'quill', replies: 2,
      spark_bounty: null },
  ],
  findings: [{ id: 14, kind: 'finding', title: 'Three replications in mice', author: 'scout' }],
  claims: [{ id: 7, state: 'supported', proposition: 'D+Q reduced senescent cells in aged mice.',
    repository: 'rrsrch/longevity', contributor: 'ominis', spark_bounty: null }],
  progress: { questions: 2, questions_open: 1, findings: 1, claims: 1, claims_by_state: { supported: 1 },
    contributors: 4, success_criteria: 2 },
};

function serve() {
  global.fetch = jest.fn(async (url) => {
    const path = url.replace('/api/engine', '');
    const ok = (body) => ({ ok: true, status: 200, json: async () => ({ ok: true, ...body }) });
    if (path === '/v1/missions/1') return ok(MISSION);
    if (path === '/v1/missions') return ok({ items: [SUMMARY] });
    return { ok: false, status: 404, json: async () => ({ ok: false, error: 'no mission 9' }) };
  });
}

afterEach(() => window.history.replaceState(null, '', '/'));

test('a mission page shows its terms, progress, questions with bounties, claims and a preliminary report', async () => {
  serve();
  render(<MissionPage id={1} />);
  expect(await screen.findByRole('heading', { name: SUMMARY.title })).toBeInTheDocument();
  expect(screen.getByText('Mission 001')).toBeInTheDocument();
  expect(screen.getByText('Active')).toBeInTheDocument();
  const terms = screen.getByRole('region', { name: 'Mission terms' });
  expect(within(terms).getByText('Evidence synthesis v1')).toBeInTheDocument();
  expect(within(terms).getAllByRole('listitem')).toHaveLength(2);
  const questions = screen.getByRole('region', { name: 'Research questions' });
  const [first, second] = within(questions).getAllByRole('link');
  expect(first).toHaveAttribute('href', '/questions/12');
  expect(first).toHaveTextContent(/Bounty.*20 Sparks/);
  expect(second).toHaveTextContent('No bounty · accepting research');
  expect(second).toHaveTextContent('2 replies');
  expect(within(screen.getByRole('region', { name: 'Claims' })).getByRole('link')).toHaveAttribute('href', '/claims/7');
  const report = screen.getByRole('region', { name: 'Research report' });
  expect(report).toHaveTextContent('Preliminary: not independently verified');
  expect(within(report).getByRole('heading', { name: 'Methods' })).toBeInTheDocument();
  expect(report).toHaveTextContent('Searched PubMed.');
  expect(screen.getByRole('region', { name: 'Progress' })).toHaveTextContent('1claims decided by review');
});

test('an unknown mission says so', async () => {
  serve();
  render(<MissionPage id={9} />);
  expect(await screen.findByText('No mission 9.')).toBeInTheDocument();
});

test('a topic lists its missions with counts, and the index lists them all', async () => {
  render(<TopicMissions missions={[SUMMARY]} title="Medicine" />);
  const section = screen.getByRole('region', { name: 'Research missions' });
  expect(section).toHaveTextContent('1 open or active · 2 open questions');
  const card = within(section).getByRole('link', { name: /Do senolytic/ });
  expect(card).toHaveAttribute('href', '#/missions/1');
  expect(card).toHaveTextContent('3 questions · 2 open · 1 finding · 1 claim · 4 contributors · 1 open bounty');
  expect(card).toHaveTextContent('Featured');
  serve();
  render(<MissionsIndex />);
  expect(await screen.findByRole('heading', { name: 'Research missions' })).toBeInTheDocument();
  const { container } = render(<TopicMissions missions={[]} title="Medicine" />);
  expect(container).toBeEmptyDOMElement();
});

test('a post names the missions it belongs to', () => {
  render(<MissionChips missions={[{ id: 1, title: 'Senolytics', status: 'open' }]} />);
  expect(screen.getByRole('link', { name: 'Mission 001: Senolytics' })).toHaveAttribute('href', '#/missions/1');
});

test('#/missions and #/missions/N are routes', () => {
  window.history.replaceState(null, '', '/#/missions/3');
  expect(currentRoute()).toBe('missions/3');
  window.history.replaceState(null, '', '/#/missions');
  expect(currentRoute()).toBe('missions');
});

test('a report shows # headings, - lists and paragraphs, and nothing else is interpreted', () => {
  render(<Report text={'# Results\n- Reproduced in mice\n- Not in rats\n\nTwo labs agree.\nOne does not.\n\n<b>raw</b>'} />);
  expect(screen.getByRole('heading', { name: 'Results' })).toBeInTheDocument();
  expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Reproduced in mice', 'Not in rats']);
  expect(screen.getByText(/Two labs agree\.\s+One does not\./)).toBeInTheDocument();
  expect(screen.getByText('<b>raw</b>')).toBeInTheDocument();
});
