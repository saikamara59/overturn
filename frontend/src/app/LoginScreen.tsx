import { useState } from 'react';
import { login } from './api';

export function LoginScreen({ onLoggedIn }: { onLoggedIn: (email: string) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const user = await login(email, password);
      onLoggedIn(user.email);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="detail" style={{ maxWidth: 420, margin: '48px auto' }}>
      <div className="card" style={{ padding: '24px 28px' }}>
        <div className="card-title" style={{ fontSize: 17, marginBottom: 14 }}>
          Sign in to Overturn
        </div>
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Email
            <input
              type="email" value={email} required
              onChange={(e) => setEmail(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                       border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }}
            />
          </label>
          <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
            Password
            <input
              type="password" value={password} required
              onChange={(e) => setPassword(e.target.value)}
              style={{ display: 'block', width: '100%', marginTop: 4, padding: '7px 10px',
                       border: '1px solid #DBD8D1', borderRadius: 8, font: 'inherit' }}
            />
          </label>
          {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)' }}>{error}</div>}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Signing in…' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  );
}
