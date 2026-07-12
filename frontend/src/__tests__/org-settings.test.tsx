import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { OrgSettingsScreen } from '../app/OrgSettingsScreen';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());
const ok = (b: unknown, s = 200) => Promise.resolve(new Response(JSON.stringify(b), { status: s }));

function wire(overrides: Record<string, unknown> = {}) {
  const base: Record<string, unknown> = {
    '/api/v1/org': { id: 'o1', name: 'Acme RCM', role: 'admin', hasApiKey: false, apiKeyLast4: null, defaultAppealDays: 90 },
    '/api/v1/org/members': [
      { userId: 'u1', email: 'boss@acme.com', role: 'admin', joinedAt: '2026-07-01' },
      { userId: 'u2', email: 'biller@acme.com', role: 'member', joinedAt: '2026-07-02' },
    ],
    '/api/v1/org/invites': [] as unknown[],
    '/api/v1/org/csv-mappings': [
      { id: 'm1', name: 'Mapping (9 columns)', headers: ['Claim Number'], mapping: {}, lastUsedAt: '2026-07-11' },
    ] as unknown[],
    ...overrides,
  };
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT' && url === '/api/v1/org/api-key') {
      (base['/api/v1/org'] as any).hasApiKey = true;
      (base['/api/v1/org'] as any).apiKeyLast4 = 'wxyz';
      return ok({ hasApiKey: true, apiKeyLast4: 'wxyz' });
    }
    if (init?.method === 'POST' && url === '/api/v1/org/invites') {
      const invite = { id: 'i1', token: 't', inviteUrl: 'http://x/#/invite/t', role: 'member', email: null, expiresAt: '2099-01-01' };
      (base['/api/v1/org/invites'] as any[]).push(invite);
      return ok(invite);
    }
    if (init?.method === 'PATCH' && url === '/api/v1/org') {
      const body = JSON.parse((init.body as string) ?? '{}');
      Object.assign(base['/api/v1/org'] as object, body);
      return ok(base['/api/v1/org']);
    }
    if (init?.method === 'DELETE' && url.startsWith('/api/v1/org/csv-mappings/')) {
      const id = url.split('/').pop();
      base['/api/v1/org/csv-mappings'] =
        (base['/api/v1/org/csv-mappings'] as any[]).filter((m) => m.id !== id);
      return ok({ deleted: id });
    }
    if (url in base) return ok(base[url]);
    return ok({}, 404);
  });
}

test('renders members, sets API key, shows last4', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  expect(await screen.findByText('boss@acme.com')).toBeInTheDocument();
  expect(screen.getByText('biller@acme.com')).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText(/anthropic api key/i), 'sk-ant-test0123456789wxyz');
  await userEvent.click(screen.getByRole('button', { name: /save key/i }));
  expect(await screen.findByText(/wxyz/)).toBeInTheDocument();
});

test('creates an invite and shows the copyable link', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  await screen.findByText('boss@acme.com');
  await userEvent.click(screen.getByRole('button', { name: /create invite/i }));
  const link = await screen.findByDisplayValue('http://x/#/invite/t');
  expect(link).toBeInTheDocument();
});

test('default appeal window edits via PATCH', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  const input = await screen.findByLabelText(/appeal window/i);
  expect(input).toHaveValue(90);
  await userEvent.clear(input);
  await userEvent.type(input, '120');
  await userEvent.click(screen.getByRole('button', { name: /save window/i }));
  const patch = fetchMock.mock.calls.find(
    ([url, init]) => url === '/api/v1/org' && (init as RequestInit)?.method === 'PATCH');
  expect(patch).toBeTruthy();
  expect(JSON.parse((patch![1] as RequestInit).body as string))
    .toEqual({ defaultAppealDays: 120 });
});

test('saved mappings list renders and deletes', async () => {
  wire();
  render(<OrgSettingsScreen onBack={() => {}} />);
  expect(await screen.findByText('Mapping (9 columns)')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /delete mapping/i }));
  const del = fetchMock.mock.calls.find(
    ([url, init]) => url === '/api/v1/org/csv-mappings/m1'
      && (init as RequestInit)?.method === 'DELETE');
  expect(del).toBeTruthy();
});
