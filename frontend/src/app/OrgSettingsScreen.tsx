import { useCallback, useEffect, useState } from 'react';
import {
  clearOrgApiKey, createInvite, getOrg, listInvites, listMembers,
  removeMember, revokeInvite, setMemberRole, setOrgApiKey,
  type InviteInfo, type MemberInfo, type OrgInfo,
} from './api';

export function OrgSettingsScreen({ onBack }: { onBack: () => void }) {
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [invites, setInvites] = useState<InviteInfo[]>([]);
  const [keyInput, setKeyInput] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    getOrg().then(setOrg).catch((e) => setError(String(e.message ?? e)));
    listMembers().then(setMembers).catch(() => {});
    listInvites().then(setInvites).catch(() => {});
  }, []);
  useEffect(refresh, [refresh]);

  if (!org) return <div className="sm-note" style={{ padding: 24 }}>{error || 'Loading…'}</div>;

  const act = (p: Promise<unknown>) =>
    p.then(refresh).catch((e) => setError(String((e as Error).message ?? e)));

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Org Settings — {org.name}</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to runs</button>
      </div>
      {error && <div style={{ color: 'var(--red-fg)', fontSize: 12.5, marginTop: 8 }}>{error}</div>}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Anthropic API key</div>
        <div className="sm-note" style={{ marginTop: 6 }}>
          {org.hasApiKey
            ? `A key ending in ${org.apiKeyLast4} is configured — live runs bill your organization.`
            : 'No key configured — uploads run in dry-run mode (no Claude refinement).'}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)', flex: 1, minWidth: 260 }}>
            Anthropic API key
            <input type="password" value={keyInput} placeholder="sk-ant-…"
                   onChange={(e) => setKeyInput(e.target.value)}
                   style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="button" className="btn-primary"
                  onClick={() => act(setOrgApiKey(keyInput)).then(() => setKeyInput(''))}>
            Save key
          </button>
          {org.hasApiKey && (
            <button type="button" className="btn" onClick={() => act(clearOrgApiKey())}>
              Remove key
            </button>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Members</div>
        <div style={{ marginTop: 8 }}>
          {members.map((m) => (
            <div key={m.userId} className="audit-row" style={{ gap: 14 }}>
              <div style={{ flex: 1, fontSize: 13 }}>{m.email}</div>
              <select value={m.role} style={{ font: 'inherit', fontSize: 12.5 }}
                      onChange={(e) => act(setMemberRole(m.userId, e.target.value))}>
                <option value="admin">admin</option>
                <option value="member">member</option>
              </select>
              <button type="button" className="btn" onClick={() => act(removeMember(m.userId))}>
                Remove
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Invites</div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
          <select value={inviteRole} style={{ font: 'inherit', fontSize: 12.5 }}
                  onChange={(e) => setInviteRole(e.target.value)}>
            <option value="member">member</option>
            <option value="admin">admin</option>
          </select>
          <button type="button" className="btn-primary"
                  onClick={() => act(createInvite(inviteRole))}>
            Create invite
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          {invites.length === 0 && <div className="sm-note">No pending invites.</div>}
          {invites.map((inv) => (
            <div key={inv.id} className="audit-row" style={{ gap: 10 }}>
              <span className="pill c-blue">{inv.role}</span>
              <input readOnly value={inv.inviteUrl}
                     style={{ flex: 1, font: 'inherit', fontSize: 12, padding: '4px 8px',
                              border: '1px solid var(--line-2)', borderRadius: 6 }}
                     onFocus={(e) => e.target.select()} />
              <button type="button" className="btn"
                      onClick={() => navigator.clipboard?.writeText(inv.inviteUrl)}>
                Copy
              </button>
              <button type="button" className="btn" onClick={() => act(revokeInvite(inv.id))}>
                Revoke
              </button>
            </div>
          ))}
        </div>
        <div className="sm-note" style={{ marginTop: 8 }}>
          Invite links are single-use and expire after 7 days. Password reset:
          create a new invite for the same email.
        </div>
      </div>
    </div></div>
  );
}
