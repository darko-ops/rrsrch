import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import FeatureButton, { isNetworkAdmin } from './FeatureButton';

const ADMIN = { ok: true, handle: 'ops', organization_id: 'rrsrch', org_role: 'admin', status: 'active',
  scopes: ['agents', 'propose', 'read'] };

function mock(me) {
  const calls = [];
  global.fetch = jest.fn(async (url, opts = {}) => {
    calls.push({ url, opts });
    const body = url.includes('/v1/whoami') ? me : { ok: true, featured: true };
    return { ok: true, status: 200, json: async () => body };
  });
  return calls;
}

test('only an active rrsrch admin with the agents scope counts as a network admin', () => {
  expect(isNetworkAdmin(ADMIN)).toBe(true);
  expect(isNetworkAdmin({ ...ADMIN, organization_id: 'people' })).toBe(false);   // a site sign-in
  expect(isNetworkAdmin({ ...ADMIN, org_role: 'member' })).toBe(false);
  expect(isNetworkAdmin({ ...ADMIN, scopes: ['read'] })).toBe(false);
  expect(isNetworkAdmin(null)).toBe(false);
});

test('an admin features a finding, and the page reloads', async () => {
  const calls = mock(ADMIN);
  const onChanged = jest.fn();
  render(<FeatureButton path="posts/7" featured={false} apiKey="k" onChanged={onChanged} what="posts once" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Feature on X' }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  const sent = calls.find((c) => c.url.includes('/v1/posts/7/feature'));
  expect(sent.opts.method).toBe('POST');
  expect(JSON.parse(sent.opts.body)).toEqual({ featured: true });
});

test('a featured gauge offers Unfeature', async () => {
  mock(ADMIN);
  render(<FeatureButton path="gauges/clean-power" featured apiKey="k" onChanged={() => {}} />);
  expect(await screen.findByRole('button', { name: 'Unfeature' })).toBeInTheDocument();
});

test('nobody else sees the button', async () => {
  const calls = mock({ ...ADMIN, organization_id: 'people' });
  const { container } = render(<FeatureButton path="posts/7" featured={false} apiKey="k" onChanged={() => {}} />);
  await waitFor(() => expect(calls.some((c) => c.url.includes('/v1/whoami'))).toBe(true));
  expect(container).toBeEmptyDOMElement();
  render(<FeatureButton path="posts/7" featured={false} apiKey="" onChanged={() => {}} />);
  expect(screen.queryByRole('button')).toBeNull();
});
