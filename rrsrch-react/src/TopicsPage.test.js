import { render, screen, fireEvent, within } from '@testing-library/react';
import TopicsPage from './TopicsPage';
import CollectionPicker, { groupCollections } from './CollectionPicker';
import { resetTopics, indexTopics } from './topicTree';

const n = (collections, claims, posts) => ({ collections, claims, posts });
const t = (slug, title, parent, total = n(0, 0, 0), description = '') => ({ slug, title, parent, description, own: n(0, 0, 0), total });
const TREE = [
  t('medicine', 'Medicine', null, n(1, 695, 5), 'Health, disease and treatment'),
  t('musculoskeletal', 'Musculoskeletal', 'medicine', n(1, 695, 5)),
  t('knee-oa', 'Knee osteoarthritis', 'musculoskeletal', n(1, 695, 5)),
  t('regenerative-medicine', 'Regenerative medicine', 'medicine'),
  t('msc', 'Mesenchymal stromal cells', 'regenerative-medicine', n(0, 0, 4)),
  t('technology', 'Technology', null, n(1, 0, 1)),
  t('semiconductors', 'Semiconductors', 'technology', n(1, 0, 1)),
];
const REPOS = [
  { slug: 'rrsrch/msc-knee-oa', topic: 'MSC therapy for knee OA', topic_slug: 'knee-oa', claims: 695 },
  { slug: 'ominis-labs/semis-robotics', topic: 'semiconductors', topic_slug: 'semiconductors', claims: 0 },
  { slug: 'rrsrch/network', topic: 'The research network', topic_slug: null, claims: 0 },
];
const MUSCULO = { slug: 'musculoskeletal', title: 'Musculoskeletal', description: 'Bones, joints and muscles', parent: 'medicine',
  path: [{ slug: 'medicine', title: 'Medicine' }, { slug: 'musculoskeletal', title: 'Musculoskeletal' }],
  total: n(1, 695, 5), children: [{ slug: 'knee-oa', title: 'Knee osteoarthritis', description: '', total: n(1, 695, 5) }],
  collections: [] };

function serve({ me = null, posted = [] } = {}) {
  global.fetch = jest.fn(async (url, opts = {}) => {
    const path = url.replace('/api/engine', '');
    const ok = (body) => ({ ok: true, status: 200, json: async () => ({ ok: true, ...body }) });
    if (opts.method === 'POST' && path === '/v1/topics') {
      posted.push(JSON.parse(opts.body));
      TREE.push(t('hip-oa', 'Hip osteoarthritis', 'musculoskeletal'));
      return { ok: true, status: 201, json: async () => ({ ok: true, topic: { slug: 'hip-oa' } }) };
    }
    if (path === '/v1/topics') return ok({ items: TREE });
    if (path === '/v1/topics/musculoskeletal') return ok({ topic: MUSCULO });
    if (path === '/v1/whoami') return me ? ok(me) : { ok: false, status: 401, json: async () => ({ ok: false }) };
    if (path.startsWith('/v1/explore')) return ok({ items: [], topics: [], kind_counts: {} });
    if (path.startsWith('/v1/subscriptions')) return ok({ subscriptions: [] });
    return { ok: false, status: 404, json: async () => ({ ok: false, error: 'not found' }) };
  });
  return posted;
}

beforeEach(() => resetTopics());
afterEach(() => { localStorage.clear(); window.history.replaceState(null, '', '/'); });

test('the index shows every top-level topic with what is under it, and the tree expands and filters', async () => {
  serve();
  render(<TopicsPage isMobile={false} />);
  expect(await screen.findByRole('heading', { name: 'Topics' })).toBeInTheDocument();
  const med = screen.getAllByRole('link', { name: /^Medicine/ }).find((a) => a.textContent.includes('Health'));
  expect(med).toHaveAttribute('href', '/topics/medicine');
  expect(med).toHaveTextContent('1 collection · 695 claims · 5 posts');
  expect(med).toHaveTextContent('Musculoskeletal · Regenerative medicine');            // its sub-topics
  const tree = screen.getByRole('tree', { name: 'Topics' });
  expect(within(tree).queryByText('Knee osteoarthritis')).not.toBeInTheDocument();       // collapsed
  fireEvent.click(within(tree).getByRole('button', { name: 'Expand Medicine' }));
  fireEvent.click(within(tree).getByRole('button', { name: 'Expand Musculoskeletal' }));
  expect(within(tree).getByText('Knee osteoarthritis')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Filter topics'), { target: { value: 'semi' } });
  expect(within(tree).getByText('Semiconductors')).toBeInTheDocument();                  // the match and its parent
  expect(within(tree).getByText('Technology')).toBeInTheDocument();
  expect(within(tree).queryByText('Medicine')).not.toBeInTheDocument();
});

test('a topic shows its path, sub-topics and collections; an organization admin adds a sub-topic', async () => {
  localStorage.setItem('rrsrch_engine_key', 'rrsrch_k');
  const posted = serve({ me: { handle: 'lab-admin', organization_id: 'lab', org_role: 'admin', scopes: ['read'] } });
  render(<TopicsPage slug="musculoskeletal" isMobile={false} />);
  expect(await screen.findByRole('heading', { name: 'Musculoskeletal' })).toBeInTheDocument();
  const path = screen.getByRole('navigation', { name: 'Topic path' });
  expect(within(path).getByText('Medicine')).toHaveAttribute('href', '/topics/medicine');
  expect(screen.getByRole('treeitem', { name: /Musculoskeletal/, selected: true })).toBeInTheDocument();  // open in the tree
  const subs = screen.getByRole('region', { name: 'Sub-topics' });
  expect(within(subs).getByRole('link', { name: /Knee osteoarthritis/ })).toHaveAttribute('href', '/topics/knee-oa');
  expect(screen.getByRole('region', { name: 'Collections' })).toHaveTextContent('its sub-topics may have some');
  expect(screen.getByRole('region', { name: 'Questions and findings' })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: 'Add a sub-topic' }));
  fireEvent.change(screen.getByLabelText('Sub-topic title'), { target: { value: 'Hip osteoarthritis' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add it' }));
  await screen.findByText('Hip osteoarthritis');
  expect(posted).toEqual([{ title: 'Hip osteoarthritis', parent: 'musculoskeletal', description: '' }]);
  expect(window.location.pathname).toBe('/topics/hip-oa');
});

test('signed out, a topic has no follow or add buttons', async () => {
  serve();
  render(<TopicsPage slug="musculoskeletal" isMobile={false} />);
  await screen.findByRole('heading', { name: 'Musculoskeletal' });
  expect(screen.queryByRole('button', { name: 'Follow' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Add a sub-topic' })).not.toBeInTheDocument();
});

test('the collection picker groups collections by topic path, searches, and picks with the keyboard', async () => {
  const tree = indexTopics(TREE);
  const groups = groupCollections(REPOS, tree);
  expect(groups.map((g) => g.where)).toEqual(['Medicine › Musculoskeletal › Knee osteoarthritis',
    'Technology › Semiconductors', 'Not filed under a topic']);
  expect(groupCollections(REPOS, tree, 'technology').map((g) => g.items[0].slug)).toEqual(['ominis-labs/semis-robotics']);

  serve();
  const picked = [];
  render(<CollectionPicker repos={REPOS} repo="rrsrch/msc-knee-oa" onRepo={(s) => picked.push(s)} />);
  const button = screen.getByRole('button', { name: 'Collection: rrsrch/msc-knee-oa' });
  expect(await within(button).findByText('Knee osteoarthritis')).toBeInTheDocument();     // where it sits
  fireEvent.click(button);
  const dialog = screen.getByRole('dialog', { name: 'Choose a collection' });
  expect(within(dialog).getAllByRole('option')).toHaveLength(3);
  fireEvent.change(within(dialog).getByLabelText('Find a collection'), { target: { value: 'semi' } });
  expect(within(dialog).getAllByRole('option')).toHaveLength(1);
  fireEvent.keyDown(within(dialog).getByLabelText('Find a collection'), { key: 'Enter' });
  expect(picked).toEqual(['ominis-labs/semis-robotics']);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  fireEvent.click(button);
  fireEvent.keyDown(screen.getByLabelText('Find a collection'), { key: 'ArrowDown' });
  fireEvent.keyDown(screen.getByLabelText('Find a collection'), { key: 'Enter' });
  expect(picked).toEqual(['ominis-labs/semis-robotics', 'ominis-labs/semis-robotics']);
  fireEvent.click(button);
  expect(screen.getByRole('link', { name: /Browse every topic/ })).toHaveAttribute('href', '#/topics');
  fireEvent.keyDown(screen.getByLabelText('Find a collection'), { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
