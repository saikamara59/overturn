import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ServerApp } from '../app/ServerApp';
import { SAMPLE_DATA } from '../fixtures/sample';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

const RUN = {
  id: 'r1', filename: 'denials.csv', dryRun: true, isDemo: false,
  status: 'completed', totalRecords: 3, drafted: 3, failedRecords: 0,
  totalBilled: 21230.25, error: null,
  createdAt: '2026-07-08T00:00:00Z', startedAt: null, finishedAt: null,
};

beforeEach(() => { window.location.hash = ''; });
afterEach(() => fetchMock.mockReset());

test('logged out: demo workbench with sign-in affordance', async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/demo/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText(/synthetic/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  expect(await screen.findByText('CLM-0001')).toBeInTheDocument();
});

test('login flow reaches the runs screen', async () => {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/auth/me') return ok({ detail: 'x' }, 401);
    if (url === '/api/v1/auth/login') return ok({ email: 'a@b.c' });
    if (url === '/api/v1/runs' && (!init || !init.method)) return ok([RUN]);
    if (url === '/api/v1/demo/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  await userEvent.click(await screen.findByRole('button', { name: /sign in/i }));
  await userEvent.type(screen.getByLabelText(/email/i), 'a@b.c');
  await userEvent.type(screen.getByLabelText(/password/i), 'pw');
  await userEvent.click(screen.getByRole('button', { name: /log in/i }));
  expect(await screen.findByText('denials.csv')).toBeInTheDocument();
  expect(screen.getByText(/3 \/ 3 drafted/)).toBeInTheDocument();
});

test('opening a run loads the workbench via hash route', async () => {
  window.location.hash = '#/runs/r1';
  fetchMock.mockImplementation((url: string) => {
    if (url === '/api/v1/auth/me') return ok({ email: 'a@b.c' });
    if (url === '/api/v1/runs/r1') return ok(RUN);
    if (url === '/api/v1/runs/r1/claims') return ok(SAMPLE_DATA);
    return ok({}, 404);
  });
  render(<ServerApp />);
  expect(await screen.findByText('CLM-0001')).toBeInTheDocument();
  await waitFor(() =>
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain('/api/v1/runs/r1/claims'),
  );
});
