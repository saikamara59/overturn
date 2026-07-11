import Papa from 'papaparse';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fmtMoney } from '../lib/format';
import { CANONICAL, MappingPanel, headerKey } from './MappingPanel';
import {
  ApiError, listCsvMappings, listRuns, retryRun, uploadRun,
  getOrg, type CsvMappingSpec, type OrgInfo, type RowError, type RunInfo,
  type SavedCsvMapping,
} from './api';

const ACTIVE = new Set(['queued', 'running']);

interface Staged {
  file: File;
  headers: string[];
  samples: Record<string, string>[];
}

export function RunsScreen({ onOpenRun }: { onOpenRun: (id: string) => void }) {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [dryRun, setDryRun] = useState(true);
  const [error, setError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const [savedMappings, setSavedMappings] = useState<SavedCsvMapping[]>([]);
  const [orgInfo, setOrgInfo] = useState<OrgInfo | null>(null);
  const [staged, setStaged] = useState<Staged | null>(null);
  const [mappingNeeded, setMappingNeeded] = useState(false);
  const [activeMapping, setActiveMapping] = useState<CsvMappingSpec | null>(null);
  const [usingSaved, setUsingSaved] = useState(false);
  const [saveMapping, setSaveMapping] = useState(false);
  const [rowErrors, setRowErrors] = useState<RowError[] | null>(null);
  const [totalErrors, setTotalErrors] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setRuns(await listRuns());
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  }, []);

  useEffect(() => {
    refresh();
    listCsvMappings().then(setSavedMappings).catch(() => {});
    getOrg().then(setOrgInfo).catch(() => {});
  }, [refresh]);

  useEffect(() => {
    if (!runs.some((r) => ACTIVE.has(r.status))) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [runs, refresh]);

  const resetStaged = () => {
    setStaged(null);
    setMappingNeeded(false);
    setActiveMapping(null);
    setUsingSaved(false);
    setSaveMapping(false);
  };

  const onFileChange = () => {
    const file = fileRef.current?.files?.[0];
    setError('');
    setRowErrors(null);
    resetStaged();
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setStaged({ file, headers: [], samples: [] });
      return;
    }
    Papa.parse<Record<string, string>>(file, {
      header: true,
      preview: 5,
      skipEmptyLines: true,
      complete: (results) => {
        const headers = results.meta.fields ?? [];
        const samples = results.data ?? [];
        setStaged({ file, headers, samples });

        const requiredNames = CANONICAL.filter((f) => f.required).map((f) => f.key);
        const hasAllCanonical = requiredNames.every((name) => headers.includes(name));
        if (hasAllCanonical) {
          setMappingNeeded(false);
          return;
        }

        const key = headerKey(headers);
        const hit = savedMappings.find((m) => headerKey(m.headers) === key);
        if (hit) {
          setActiveMapping(hit.mapping);
          setUsingSaved(true);
          setMappingNeeded(false);
        } else {
          setMappingNeeded(true);
        }
      },
    });
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const file = staged?.file;
    if (!file) return;
    setError('');
    setRowErrors(null);
    try {
      await uploadRun(file, dryRun, activeMapping ? { mapping: activeMapping, saveMapping } : undefined);
      if (fileRef.current) fileRef.current.value = '';
      resetStaged();
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.detail && typeof err.detail === 'object'
          && 'errors' in (err.detail as Record<string, unknown>)) {
        const d = err.detail as { errors: RowError[]; totalErrors: number };
        setRowErrors(d.errors);
        setTotalErrors(d.totalErrors);
      } else {
        setError(String((err as Error).message ?? err));
      }
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
          <input ref={fileRef} type="file" accept=".csv,.json" required
                 onChange={onFileChange} style={{ font: 'inherit', fontSize: 13 }} />
          {usingSaved && (
            <>
              <span className="pill c-green">using saved mapping ✓</span>
              <button type="button" className="btn" onClick={() => setMappingNeeded(true)}>Edit</button>
            </>
          )}
          <label style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (no Claude refinement, no API cost)
          </label>
          <button type="submit" className="btn-primary" disabled={mappingNeeded}>
            Upload &amp; draft appeals
          </button>
        </form>
        <div className="sm-note" style={{ marginTop: 10 }}>
          Simplified-835 CSV or JSON. Do not upload real PHI — this deployment is not BAA-covered.
        </div>
        {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)', marginTop: 8 }}>{error}</div>}
        {mappingNeeded && staged && (
          <MappingPanel
            headers={staged.headers}
            sampleRows={staged.samples}
            defaultAppealDays={orgInfo?.defaultAppealDays ?? 90}
            initial={usingSaved ? activeMapping ?? undefined : undefined}
            onConfirm={(mapping, remember) => {
              setActiveMapping(mapping);
              setSaveMapping(remember);
              setUsingSaved(false);
              setMappingNeeded(false);
            }}
            onCancel={() => setMappingNeeded(false)}
          />
        )}
        {rowErrors && (
          <div className="panel" style={{ marginTop: 10 }}>
            <div className="panel-title" style={{ color: 'var(--red-fg)' }}>
              {totalErrors} row error{totalErrors === 1 ? '' : 's'} — nothing was imported
            </div>
            <div style={{ marginTop: 6 }}>
              {rowErrors.map((e, i) => (
                <div key={i} className="audit-row" style={{ gap: 10 }}>
                  <span className="pill c-red">row {e.row + 1}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5 }}>{e.field}</span>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5,
                                 color: 'var(--mut)' }}>{e.value}</span>
                  <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{e.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
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
