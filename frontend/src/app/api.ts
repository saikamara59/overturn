import type { AuditEvent, Claim, WorkbenchData } from '../types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface MeInfo {
  email: string; orgId: string; orgName: string;
  role: 'admin' | 'member'; isPlatformAdmin: boolean;
}
export interface OrgInfo { id: string; name: string; role: string; hasApiKey: boolean; apiKeyLast4: string | null }
export interface MemberInfo { userId: string; email: string; role: string; joinedAt: string }
export interface InviteInfo { id: string; token: string; inviteUrl: string; role: string; email: string | null; expiresAt: string }
export interface InvitePeek { orgName: string; role: string; email: string | null; expiresAt: string }
export interface AdminOrg { id: string; name: string; status: string; members: number; runs: number }

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
  request<MeInfo>('/api/v1/auth/login', json('POST', { email, password }));

export const logout = () => request<{ ok: boolean }>('/api/v1/auth/logout', { method: 'POST' });

export async function me(): Promise<MeInfo | null> {
  try {
    return await request<MeInfo>('/api/v1/auth/me');
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export const getOrg = () => request<OrgInfo>('/api/v1/org');
export const setOrgApiKey = (key: string) =>
  request<{ hasApiKey: boolean; apiKeyLast4: string }>('/api/v1/org/api-key', json('PUT', { key }));
export const clearOrgApiKey = () =>
  request<{ hasApiKey: boolean }>('/api/v1/org/api-key', { method: 'DELETE' });
export const listMembers = () => request<MemberInfo[]>('/api/v1/org/members');
export const setMemberRole = (userId: string, role: string) =>
  request<{ userId: string; role: string }>(`/api/v1/org/members/${userId}`, json('PATCH', { role }));
export const removeMember = (userId: string) =>
  request<{ removed: string }>(`/api/v1/org/members/${userId}`, { method: 'DELETE' });
export const createInvite = (role: string, email?: string) =>
  request<InviteInfo>('/api/v1/org/invites', json('POST', { role, email: email || null }));
export const listInvites = () => request<InviteInfo[]>('/api/v1/org/invites');
export const revokeInvite = (id: string) =>
  request<{ revoked: string }>(`/api/v1/org/invites/${id}`, { method: 'DELETE' });
export const peekInvite = (token: string) => request<InvitePeek>(`/api/v1/invites/${token}`);
export const acceptInvite = (token: string, email: string, password: string) =>
  request<MeInfo>(`/api/v1/invites/${token}/accept`, json('POST', { email, password }));
export const adminListOrgs = () => request<AdminOrg[]>('/api/v1/admin/orgs');
export const adminCreateOrg = (name: string) =>
  request<{ org: AdminOrg; inviteUrl: string; token: string }>('/api/v1/admin/orgs', json('POST', { name }));
export const adminSetOrgStatus = (id: string, status: string) =>
  request<{ id: string; status: string }>(`/api/v1/admin/orgs/${id}`, json('PATCH', { status }));

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
  body: { letter?: string | null; status?: 'submitted' | 'dismissed' | 'restored'; dismissReason?: string | null },
) => request<Claim>(`/api/v1/claims/${dbId}`, json('PATCH', body));
