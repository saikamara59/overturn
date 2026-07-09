import type { AuditEvent, Claim, WorkbenchData } from '../types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface RunInfo {
  id: string;
  filename: string;
  dryRun: boolean;
  isDemo: boolean;
  status: 'queued' | 'running' | 'completed' | 'failed';
  totalRecords: number;
  drafted: number;
  failedRecords: number;
  totalBilled: number;
  error: string | null;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: 'same-origin', ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch { /* non-json error body */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const login = (email: string, password: string) =>
  request<{ email: string }>('/api/v1/auth/login', json('POST', { email, password }));

export const logout = () => request<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' });

export async function me(): Promise<{ email: string } | null> {
  try {
    return await request<{ email: string }>('/api/v1/auth/me');
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export function uploadRun(file: File, dryRun: boolean): Promise<{ runId: string }> {
  const body = new FormData();
  body.append('file', file);
  body.append('dry_run', String(dryRun));
  return request('/api/v1/runs', { method: 'POST', body });
}

export const listRuns = () => request<RunInfo[]>('/api/v1/runs');
export const getRun = (id: string) => request<RunInfo>(`/api/v1/runs/${id}`);
export const retryRun = (id: string) =>
  request<{ requeued: number }>(`/api/v1/runs/${id}/retry`, { method: 'POST' });
export const getRunClaims = (id: string) =>
  request<WorkbenchData>(`/api/v1/runs/${id}/claims`);
export const getRunAudit = (id: string) =>
  request<AuditEvent[]>(`/api/v1/runs/${id}/audit`);
export const getDemoClaims = () => request<WorkbenchData>('/api/v1/demo/claims');
export const getDemoAudit = () => request<AuditEvent[]>('/api/v1/demo/audit');
export const patchClaim = (
  dbId: string,
  body: { letter?: string | null; status?: 'submitted' },
) => request<Claim>(`/api/v1/claims/${dbId}`, json('PATCH', body));
