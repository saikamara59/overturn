import { useCallback, useEffect, useState } from 'react';
import {
  clearOrgApiKey, createInvite, deleteCsvMapping, getOrg, listCsvMappings, listInvites,
  listMembers, patchOrg, removeMember, revokeInvite, setMemberRole, setOrgApiKey,
  type InviteInfo, type MemberInfo, type OrgInfo, type SavedCsvMapping,
} from './api';

export function OrgSettingsScreen({ onBack }: { onBack: () => void }) {
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [members, setMembers] = useState<MemberInfo[]>([]);
  const [invites, setInvites] = useState<InviteInfo[]>([]);
  const [mappings, setMappings] = useState<SavedCsvMapping[]>([]);
  const [keyInput, setKeyInput] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [days, setDays] = useState<number | ''>('');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    getOrg().then((o) => { setOrg(o); setDays(o.defaultAppealDays); })
      .catch((e) => setError(String(e.message ?? e)));
    listMembers().then(setMembers).catch(() => {});
    listInvites().then(setInvites).catch(() => {});
    listCsvMappings().then(setMappings).catch(() => {});
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
        <div className="panel-title">Default appeal window</div>
        <div className="sm-note" style={{ marginTop: 6 }}>
          When an uploaded file has no appeal-deadline column, deadlines are
          computed as denial date + this many days.
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Appeal window (days)
            <input type="number" min={1} max={365} value={days}
                   onChange={(e) => setDays(e.target.value === '' ? '' : Number(e.target.value))}
                   style={{ display: 'block', marginTop: 4, padding: '7px 10px', width: 120,
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="button" className="btn-primary"
                  onClick={() => typeof days === 'number' && act(patchOrg(days))}>
            Save window
          </button>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Saved CSV mappings</div>
        <div style={{ marginTop: 8 }}>
          {mappings.length === 0 && (
            <div className="sm-note">No saved mappings yet — they're created
            when you map an upload and tick "Remember this mapping".</div>
          )}
          {mappings.map((m) => (
            <div key={m.id} className="audit-row" style={{ gap: 12 }}>
              <div style={{ flex: 1, fontSize: 13 }}>{m.name}</div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                {m.headers.length} columns · last used {m.lastUsedAt.slice(0, 10)}
              </div>
              <button type="button" className="btn" aria-label="delete mapping"
                      onClick={() => act(deleteCsvMapping(m.id))}>
                Delete
              </button>
            </div>
          ))}
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
