import { useCallback, useEffect, useRef, useState } from 'react';
import { fmtMoney } from '../lib/format';
import { listRuns, retryRun, uploadRun, type RunInfo } from './api';

const ACTIVE = new Set(['queued', 'running']);

export function RunsScreen({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [dryRun, setDryRun] = useState(true);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setRuns(await listRuns());
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!runs.some((r) => ACTIVE.has(r.status))) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [runs, refresh]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setError('');
    try {
      await uploadRun(file, dryRun);
      if (fileRef.current) fileRef.current.value = '';
      await refresh();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    }
  };

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Runs</div>
        <div className="sm-meta">synthetic data only — demonstration system, not production RCM software</div>
      </div>
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-title">New batch</div>
        <form onSubmit={submit}
              style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, flexWrap: 'wrap' }}>
          <input ref={fileRef} type="file" accept=".csv,.json" required style={{ font: 'inherit', fontSize: 13 }} />
          <label style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (no Claude refinement, no API cost)
          </label>
          <button type="submit" className="btn-primary">Upload &amp; draft appeals</button>
        </form>
        <div className="sm-note" style={{ marginTop: 10 }}>
          Simplified-835 CSV or JSON. Do not upload real PHI — this deployment is not BAA-covered.
        </div>
        {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)', marginTop: 8 }}>{error}</div>}
      </div>
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-title">Batches</div>
        <div style={{ display: 'flex', flexDirection: 'column', marginTop: 8 }}>
          {runs.length === 0 && <div className="sm-note">No runs yet — upload a remittance above.</div>}
          {runs.map((r) => {
            const done = r.drafted + r.failedRecords;
            const pct = r.totalRecords ? Math.round((done / r.totalRecords) * 100) : 0;
            return (
              <div key={r.id} className="audit-row" style={{ cursor: 'pointer', gap: 14 }}
                   onClick={() => onOpenRun(r.id)}>
                <div style={{ flex: 'none', fontFamily: 'var(--mono)', fontSize: 12 }}>{r.filename}</div>
                <span className={`pill ${r.status === 'failed' ? 'c-red' : r.status === 'completed' ? 'c-green' : 'c-amber'}`}>
                  {r.status}
                </span>
                <div className="bar-track" style={{ flex: 1, maxWidth: 220 }}>
                  <div className="bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 11.5, color: 'var(--mut)' }}>
                  {done} / {r.totalRecords} drafted · {fmtMoney(r.totalBilled)}
                </div>
                {r.status === 'failed' && (
                  <button type="button" className="btn"
                          onClick={(e) => { e.stopPropagation(); retryRun(r.id).then(refresh); }}>
                    Retry
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div></div>
  );
}
