import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ServerApp } from '../app/ServerApp';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const ME = { email: 'n@a.c', orgId: 'o1', orgName: 'Acme RCM', role: 'member', isPlatformAdmin: false };

beforeEach(() => { window.location.hash = '#/invite/tok123'; });
afterEach(() => { fetchMock.mockReset(); window.location.hash = ''; });

test('invite route renders peek info and accepts', async () => {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/invites/tok123')
      return ok({ orgName: 'Acme RCM', role: 'member', email: 'n@a.c', expiresAt: '2099-01-01' });
    if (url === '/api/v1/invites/tok123/accept' && init?.method === 'POST') return ok(ME);
    if (url === '/api/v1/runs') return ok([]);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/join Acme RCM/i)).toBeInTheDocument();
  // email prefilled from hint
  expect(screen.getByLabelText(/email/i)).toHaveValue('n@a.c');
  await userEvent.type(screen.getByLabelText(/password/i), 'freshpw123');
  await userEvent.click(screen.getByRole('button', { name: /join/i }));
  // lands on runs screen, org name visible in chrome
  expect(await screen.findByText('Runs')).toBeInTheDocument();
  expect(screen.getByText('Acme RCM')).toBeInTheDocument();
});

test('dead invite shows the error state', async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/invites/tok123') return ok({ detail: 'gone' }, 410);
    if (url === '/api/v1/demo/claims') return ok({ claims: [], audit: [], summary: { processed: 0, drafts: 0, failed: 0 }, totalBilled: 0, generatedOn: null, asOf: null, model: null });
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/no longer valid/i)).toBeInTheDocument();
});
