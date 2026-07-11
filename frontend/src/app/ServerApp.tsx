import { useCallback, useEffect, useState } from 'react';
import App, { type WorkbenchMutations } from '../App';
import type { WorkbenchData } from '../types';
import { AcceptInviteScreen } from './AcceptInviteScreen';
import {
  getDemoClaims, getRun, getRunClaims, logout, me, type MeInfo, patchClaim,
} from './api';
import { LoginScreen } from './LoginScreen';
import { OrgSettingsScreen } from './OrgSettingsScreen';
import { RunsScreen } from './RunsScreen';

type Route =
  | { name: 'runs' }
  | { name: 'run'; id: string }
  | { name: 'invite'; token: string }
  | { name: 'org' }
  | { name: 'admin' };

function parseHash(): Route {
  const invite = window.location.hash.match(/^#\/invite\/(.+)$/);
  if (invite) return { name: 'invite', token: invite[1] };
  if (window.location.hash === '#/org') return { name: 'org' };
  if (window.location.hash === '#/admin') return { name: 'admin' };
  const m = window.location.hash.match(/^#\/runs\/(.+)$/);
  return m ? { name: 'run', id: m[1] } : { name: 'runs' };
}

function makeMutations(): WorkbenchMutations {
  return {
    async approve(c) {
      if (!c.dbId) throw new Error('read-only view');
      await patchClaim(c.dbId, { status: 'submitted' });
    },
    async saveLetter(c, text) {
      if (!c.dbId) throw new Error('read-only view');
      await patchClaim(c.dbId, { letter: text });
    },
    async revertLetter(c) {
      if (!c.dbId) throw new Error('read-only view');
      const updated = await patchClaim(c.dbId, { letter: null });
      return updated.letter ?? '';
    },
  };
}

export function ServerApp() {
  const [user, setUser] = useState<MeInfo | null | undefined>(undefined);
  const [route, setRoute] = useState<Route>(parseHash());
  const [showLogin, setShowLogin] = useState(false);
  const [demo, setDemo] = useState<WorkbenchData | null>(null);
  const [worklist, setWorklist] = useState<WorkbenchData | null>(null);
  const [runActive, setRunActive] = useState(false);

  useEffect(() => {
    me().then(setUser);
    const onHash = () => setRoute(parseHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    if (user === null) getDemoClaims().then(setDemo).catch(() => setDemo(null));
  }, [user]);

  const loadRun = useCallback(async (id: string) => {
    const [info, data] = await Promise.all([getRun(id), getRunClaims(id)]);
    setWorklist(data);
    setRunActive(info.status === 'queued' || info.status === 'running');
  }, []);

  useEffect(() => {
    if (user && route.name === 'run') {
      setWorklist(null);
      loadRun(route.id);
    }
  }, [user, route, loadRun]);

  useEffect(() => {
    if (!runActive || route.name !== 'run') return;
    const t = setInterval(() => loadRun(route.id), 2000);
    return () => clearInterval(t);
  }, [runActive, route, loadRun]);

  if (route.name === 'invite') {
    return (
      <AcceptInviteScreen
        token={route.token}
        onAccepted={(m) => { setUser(m); window.location.hash = ''; }}
      />
    );
  }

  if (user === undefined) return null;

  if (!user) {
    if (showLogin) {
      return <LoginScreen onLoggedIn={(m) => { setUser(m); setShowLogin(false); }} />;
    }
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 20px',
                      background: 'var(--amber-bg)', color: 'var(--amber-fg)', fontSize: 12.5, fontWeight: 600 }}>
          Read-only demo — synthetic data only.
          <div className="spacer" />
          <button type="button" className="btn" onClick={() => setShowLogin(true)}>Sign in</button>
        </div>
        {demo ? <App data={demo} /> : <div className="sm-note" style={{ padding: 24 }}>Loading demo…</div>}
      </div>
    );
  }

  const chrome = (body: JSX.Element) => (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12,
                    padding: '8px 20px', borderBottom: '1px solid var(--line)',
                    fontSize: 12.5 }}>
        <span style={{ fontWeight: 650 }}>{user.orgName}</span>
        <div className="spacer" />
        {user.role === 'admin' && (
          <button type="button" className="btn"
                  onClick={() => { window.location.hash = '#/org'; }}>Org Settings</button>
        )}
        {user.isPlatformAdmin && (
          <button type="button" className="btn"
                  onClick={() => { window.location.hash = '#/admin'; }}>Admin</button>
        )}
        <button type="button" className="btn"
                onClick={() => logout().then(() => { setUser(null); window.location.hash = ''; })}>
          Log out
        </button>
      </div>
      {body}
    </div>
  );

  if (route.name === 'run') {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 20px',
                      borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
          <button type="button" className="backlink" onClick={() => { window.location.hash = ''; }}>
            ← Runs
          </button>
          <span style={{ fontWeight: 650 }}>{user.orgName}</span>
          {runActive && <span className="pill c-amber">drafting in progress — refreshing</span>}
          <div className="spacer" />
          <button type="button" className="btn"
                  onClick={() => logout().then(() => { setUser(null); window.location.hash = ''; })}>
            Log out
          </button>
        </div>
        {worklist
          ? <App data={worklist} mutations={makeMutations()} />
          : <div className="sm-note" style={{ padding: 24 }}>Loading worklist…</div>}
      </div>
    );
  }

  if (route.name === 'org') {
    if (user.role !== 'admin') {
      window.location.hash = '';
      return null;
    }
    return chrome(<OrgSettingsScreen onBack={() => { window.location.hash = ''; }} />);
  }
  if (route.name === 'admin') return chrome(<div>platform admin placeholder</div>);

  return chrome(<RunsScreen onOpenRun={(id) => { window.location.hash = `#/runs/${id}`; }} />);
}
