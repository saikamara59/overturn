import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TopBar } from './components/TopBar';
import { DetailScreen } from './components/detail/DetailScreen';
import { Toast } from './components/ui/Toast';
import { WorklistScreen } from './components/worklist/WorklistScreen';
import { downloadLetter, effectiveStatus, visibleSorted } from './lib/worklist';
import {
  NO_FILTERS,
  type FilterKey, type FilterState, type Screen, type SortCol,
  type SortState, type StatusOverrides, type WorkbenchData,
} from './types';

export default function App({ data }: { data: WorkbenchData }) {
  const [screen, setScreen] = useState<Screen>('worklist');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sort, setSort] = useState<SortState>({ col: 'urgency', dir: 'asc' });
  const [filters, setFilters] = useState<FilterState>(NO_FILTERS);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [letters, setLetters] = useState<Record<string, string>>({});
  const [statusOverrides, setStatusOverrides] = useState<StatusOverrides>({});
  const [toast, setToast] = useState('');
  const toastTimer = useRef<ReturnType<typeof setTimeout>>();

  const showToast = useCallback((msg: string) => {
    clearTimeout(toastTimer.current);
    setToast(msg);
    toastTimer.current = setTimeout(() => setToast(''), 2600);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

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
          onLetterChange={(text) => setLetters((l) => ({ ...l, [claim.id]: text }))}
          onApprove={() => {
            setStatusOverrides((o) => ({ ...o, [claim.id]: 'Submitted' }));
            showToast(`${claim.id} approved — marked Submitted (this session only)`);
          }}
          onRevert={() => {
            setLetters((l) => {
              const next = { ...l };
              delete next[claim.id];
              return next;
            });
            showToast('Draft reverted to the generated letter');
          }}
          onExport={() => {
            downloadLetter(claim, letters[claim.id]);
            showToast(`Exported ${claim.id}-appeal.md`);
          }}
        />
      );
    }
  } else if (screen === 'summary') {
    body = <div>summary placeholder</div>; // Task 6
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
