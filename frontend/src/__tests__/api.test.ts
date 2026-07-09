import { afterEach, expect, test, vi } from 'vitest';
import { ApiError, getRunClaims, me, patchClaim, uploadRun } from '../app/api';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

test('me returns null on 401 instead of throwing', async () => {
  fetchMock.mockReturnValueOnce(ok({ detail: 'nope' }, 401));
  expect(await me()).toBeNull();
});

test('uploadRun posts multipart with dry_run field', async () => {
  fetchMock.mockReturnValueOnce(ok({ runId: 'r1' }, 202));
  const file = new File(['csv'], 'denials.csv', { type: 'text/csv' });
  const out = await uploadRun(file, true);
  expect(out.runId).toBe('r1');
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/runs');
  expect(init.method).toBe('POST');
  expect(init.body).toBeInstanceOf(FormData);
  expect((init.body as FormData).get('dry_run')).toBe('true');
});

test('errors carry status and server detail', async () => {
  fetchMock.mockReturnValueOnce(ok({ detail: 'cap exceeded' }, 413));
  await expect(uploadRun(new File([''], 'x.csv'), true)).rejects.toMatchObject({
    status: 413,
    message: 'cap exceeded',
  });
  fetchMock.mockReturnValueOnce(ok({ detail: 'x' }, 413));
  await expect(uploadRun(new File([''], 'x.csv'), true)).rejects.toBeInstanceOf(ApiError);
});

test('patchClaim PATCHes json body', async () => {
  fetchMock.mockReturnValueOnce(ok({ id: 'CLM-1', status: 'Submitted' }));
  await patchClaim('db-1', { status: 'submitted' });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/v1/claims/db-1');
  expect(init.method).toBe('PATCH');
  expect(JSON.parse(init.body as string)).toEqual({ status: 'submitted' });
});

test('getRunClaims hits the worklist endpoint', async () => {
  fetchMock.mockReturnValueOnce(ok({ claims: [] }));
  await getRunClaims('r1');
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/runs/r1/claims');
});
