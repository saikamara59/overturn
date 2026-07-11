import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from './components/TopBar';
import { DetailScreen } from './components/detail/DetailScreen';
import { SummaryScreen } from './components/summary/SummaryScreen';
import { Toast } from './components/ui/Toast';
import { WorklistScreen } from './components/worklist/WorklistScreen';
import { downloadLetter, effectiveStatus, visibleSorted } from './lib/worklist';
import {
  NO_FILTERS,
  type Claim,
  type FilterKey, type FilterState, type Screen, type SortCol,
  type SortState, type StatusOverrides, type WorkbenchData,
} from './types';

export interface WorkbenchMutations {
  approve(c: Claim): Promise<void>;
  saveLetter(c: Claim, text: string): Promise<void>;
  revertLetter(c: Claim): Promise<string>;
  dismiss(c: Claim, reason?: string): Promise<Claim>;
  restore(c: Claim): Promise<Claim>;
}

export default function App({
  data,
  mutations,
}: { data: WorkbenchData; mutations?: WorkbenchMutations }) {
  const [screen, setScreen] = useState<Screen>('worklist');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ col: 'urgency', dir: 'asc' });
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [letters, setLetters] = useState<Record<string, string>>({});
  const [statusOverrides, setStatusOverrides] = useState<StatusOverrides>({});
  const [dismissReasons, setDismissReasons] = useState<Record<string, string | undefined>>({});
  const [toast, setToast] = useState('');
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();
  const saveTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((msg: string) => {
    clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = setTimeout(() => setToast(''), 2600);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);
  useEffect(() => () => clearTimeout(saveTimer.current), []);

  const sorted = useMemo(
    () => visibleSorted(data.claims, filters, sort, statusOverrides),
    [data.claims, filters, sort, statusOverrides],
  );

  const onToggleFilter = (key: FilterKey, val: string) =>
    setFilters((f) => ({
      ...f,
      [key]: f[key].includes(val) ? f[key].filter((x) => x !== val) : [...f[key], val],
    }));

  const onSort = (col: SortCol) =>
    setSort((s) =>
      s.col === col
        ? { ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { col, dir: col === 'billed' ? 'desc' : 'asc' },
    );

  const onToggleAll = () => {
    const allChecked = sorted.length > 0 && sorted.every((c) => selected[c.id]);
    setSelected(allChecked ? {} : Object.fromEntries(sorted.map((c) => [c.id, true])));
  };

  const onExportSelected = () => {
    const sel = data.claims.filter((c) => selected[c.id] && c.letter);
    sel.forEach((c) => downloadLetter(c, letters[c.id]));
    showToast(`${sel.length} letter${sel.length === 1 ? '' : 's'} exported`);
  };

  let body: JSX.Element;
  if (screen === 'detail') {
    const claim = data.claims.find((c) => c.id === activeId) ?? data.claims[0];
    if (!claim) {
      body = <div className="detail">No claims in this batch.</div>;
    } else {
      body = (
        <DetailScreen
          claim={claim}
          status={effectiveStatus(claim, statusOverrides)}
          model={data.model}
          generatedOn={data.generatedOn}
          letter={letters[claim.id] ?? claim.letter ?? ''}
          onBack={() => setScreen('worklist')}
          onLetterChange={(text) => {
            setLetters((l) => ({ ...l, [claim.id]: text }));
            if (mutations) {
              clearTimeout(saveTimer.current);
              saveTimer.current = setTimeout(() => {
                mutations.saveLetter(claim, text).catch((e) => showToast(String(e.message ?? e)));
              }, 800);
            }
          }}
          onApprove={() => {
            const apply = () => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: 'Submitted' }));
              showToast(
                mutations
                  ? `${claim.id} approved — saved`
                  : `${claim.id} approved — marked Submitted (this session only)`,
              );
            };
            if (mutations) {
              mutations.approve(claim).then(apply).catch((e) => showToast(String(e.message ?? e)));
            } else {
              apply();
            }
          }}
          onRevert={() => {
            const applyLocal = (restored?: string) => {
              setLetters((l) => {
                const next = { ...l };
                if (restored !== undefined) next[claim.id] = restored;
                else delete next[claim.id];
                return next;
              });
              showToast('Draft reverted to the generated letter');
            };
            if (mutations) {
              mutations.revertLetter(claim).then(applyLocal).catch((e) => showToast(String(e.message ?? e)));
            } else {
              applyLocal();
            }
          }}
          onExport={() => {
            downloadLetter(claim, letters[claim.id]);
            showToast(`Exported ${claim.id}-appeal.md`);
          }}
          onDismiss={mutations ? (reason?: string) => {
            mutations.dismiss(claim, reason).then((updated) => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: updated.status as string }));
              setDismissReasons((d) => ({ ...d, [claim.id]: reason }));
              showToast(`${claim.id} dismissed — won't appeal`);
            }).catch((e) => showToast(String((e as Error).message ?? e)));
          } : undefined}
          onRestore={mutations ? () => {
            mutations.restore(claim).then((updated) => {
              setStatusOverrides((o) => ({ ...o, [claim.id]: updated.status as string }));
              setDismissReasons((d) => ({ ...d, [claim.id]: undefined }));
              showToast(`${claim.id} restored to the worklist`);
            }).catch((e) => showToast(String((e as Error).message ?? e)));
          } : undefined}
          dismissReason={dismissReasons[claim.id] ?? claim.dismissReason ?? undefined}
        />
      );
    }
  } else if (screen === 'summary') {
    body = (
      <SummaryScreen
        data={data}
        statusOverrides={statusOverrides}
        onBack={() => setScreen('worklist')}
      />
    );
  } else {
    body = (
      <WorklistScreen
        data={data}
        filters={filters}
        onToggleFilter={onToggleFilter}
        onResetFilters={() => setFilters(NO_FILTERS)}
        sort={sort}
        onSort={onSort}
        sorted={sorted}
        selected={selected}
        onToggleClaim={(id) => setSelected((s) => ({ ...s, [id]: !s[id] }))}
        onToggleAll={onToggleAll}
        onClearSelection={() => setSelected({})}
        onExportSelected={onExportSelected}
        onOpenClaim={(id) => { setActiveId(id); setScreen('detail'); }}
        statusOverrides={statusOverrides}
      />
    );
  }

  return (
    <div id="workbench" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <TopBar screen={screen} onNavigate={setScreen} generatedOn={data.generatedOn} asOf={data.asOf} />
      {body}
      <Toast message={toast} />
    </div>
  );
}
