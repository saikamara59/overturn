import { useEffect, useState } from 'react';
import { acceptInvite, peekInvite, type InvitePeek, type MeInfo } from './api';

export function AcceptInviteScreen({
  token, onAccepted,
}: { token: string; onAccepted: (me: MeInfo) => void }) {
  const [peek, setPeek] = useState<InvitePeek | null>(null);
  const [dead, setDead] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    peekInvite(token)
      .then((p) => { setPeek(p); if (p.email) setEmail(p.email); })
      .catch(() => setDead(true));
  }, [token]);

  if (dead) {
    return (
      <div className="detail" style={{ maxWidth: 460, margin: '48px auto' }}>
        <div className="card" style={{ padding: '24px 28px' }}>
          <div className="card-title">This invite is no longer valid</div>
          <div className="sm-note" style={{ marginTop: 8 }}>
            It may have expired or already been used. Ask your organization
            admin for a new invite link.
          </div>
        </div>
      </div>
    );
  }
  if (!peek) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      onAccepted(await acceptInvite(token, email, password));
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const input = {
    display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
    border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit',
  } as const;

  return (
    <div className="detail" style={{ maxWidth: 460, margin: '48px auto' }}>
      <div className="card" style={{ padding: '24px 28px' }}>
        <div className="card-title" style={{ fontSize: 17 }}>
          You've been invited to {peek.orgName}
        </div>
        <div className="sm-note" style={{ margin: '6px 0 14px' }}>
          Role: {peek.role}. Set your password to create your account (or
          enter your existing password if you already have one).
        </div>
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Email
            <input type="email" value={email} required style={input}
                   onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Password
            <input type="password" value={password} required minLength={8} style={input}
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)' }}>{error}</div>}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Joining…' : `Join ${peek.orgName}`}
          </button>
        </form>
      </div>
    </div>
  );
}
