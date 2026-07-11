import { useCallback, useEffect, useState } from 'react';
import {
  adminCreateOrg, adminListOrgs, adminSetOrgStatus, type AdminOrg,
} from './api';

export function PlatformAdminScreen({ onBack }: { onBack: () => void }) {
  const [orgs, setOrgs] = useState<AdminOrg[]>([]);
  const [name, setName] = useState('');
  const [lastInvite, setLastInvite] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(() => {
    adminListOrgs().then(setOrgs).catch((e) => setError(String(e.message ?? e)));
  }, []);
  useEffect(refresh, [refresh]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const out = await adminCreateOrg(name);
      setLastInvite(out.inviteUrl);
      setName('');
      refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  };

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Platform Admin</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to runs</button>
      </div>
      {error && <div style={{ color: 'var(--red-fg)', fontSize: 12.5, marginTop: 8 }}>{error}</div>}

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">Create organization</div>
        <form onSubmit={create}
              style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Organization name
            <input value={name} required onChange={(e) => setName(e.target.value)}
                   style={{ display: 'block', marginTop: 4, padding: '7px 10px',
                            border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }} />
          </label>
          <button type="submit" className="btn-primary">Create org</button>
        </form>
        {lastInvite && (
          <div style={{ display: 'flex', gap: 10, marginTop: 10, alignItems: 'center' }}>
            <span className="pill c-green">first admin invite</span>
            <input readOnly value={lastInvite} onFocus={(e) => e.target.select()}
                   style={{ flex: 1, font: 'inherit', fontSize: 12, padding: '4px 8px',
                            border: '1px solid var(--line-2)', borderRadius: 6 }} />
            <button type="button" className="btn"
                    onClick={() => navigator.clipboard?.writeText(lastInvite)}>Copy</button>
          </div>
        )}
      </div>

      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Organizations</div>
        <div style={{ marginTop: 8 }}>
          {orgs.map((o) => (
            <div key={o.id} className="audit-row" style={{ gap: 14 }}>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 550 }}>{o.name}</div>
              <span className={`pill ${o.status === 'active' ? 'c-green' : 'c-red'}`}>{o.status}</span>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                {o.members} members · {o.runs} runs
              </div>
              <button type="button" className="btn"
                      onClick={() =>
                        adminSetOrgStatus(o.id, o.status === 'active' ? 'disabled' : 'active')
                          .then(refresh)
                          .catch((e) => setError(String((e as Error).message ?? e)))}>
                {o.status === 'active' ? 'Disable' : 'Enable'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div></div>
  );
}
