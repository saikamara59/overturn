import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { PlatformAdminScreen } from '../app/PlatformAdminScreen';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());
const ok = (b: unknown, s = 200) => Promise.resolve(new Response(JSON.stringify(b), { status: s }));

test('lists orgs, creates one, shows first invite link, toggles status', async () => {
  let orgs = [
    { id: 'o1', name: 'Overturn HQ', status: 'active', members: 1, runs: 3 },
  ];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/admin/orgs' && init?.method === 'POST') {
      orgs = [...orgs, { id: 'o2', name: 'NewCo', status: 'active', members: 0, runs: 0 }];
      return ok({ org: orgs[1], inviteUrl: 'http://x/#/invite/first', token: 'first' });
    }
    if (url === '/api/v1/admin/orgs') return ok(orgs);
    if (url.startsWith('/api/v1/admin/orgs/') && init?.method === 'PATCH')
      return ok({ id: 'o2', status: 'disabled' });
    return ok({}, 404);
  });
  render(<PlatformAdminScreen onBack={() => {}} />);
  expect(await screen.findByText('Overturn HQ')).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText(/organization name/i), 'NewCo');
  await userEvent.click(screen.getByRole('button', { name: /create org/i }));
  expect(await screen.findByDisplayValue('http://x/#/invite/first')).toBeInTheDocument();
  expect(await screen.findByText('NewCo')).toBeInTheDocument();
});
