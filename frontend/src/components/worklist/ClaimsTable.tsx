import { fmtDate, fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, SortCol, SortState, StatusOverrides } from '../../types';
import { Checkbox } from '../ui/Checkbox';
import { DaysPill, StatusPill } from '../ui/Pills';

interface Props {
  sorted: Claim[];
  sort: SortState;
  onSort: (col: SortCol) => void;
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onToggleAll: () => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function ClaimsTable(p: Props) {
  const arrow = (col: SortCol) => (p.sort.col === col ? (p.sort.dir === 'asc' ? ' ↑' : ' ↓') : '');
  const allChecked = p.sorted.length > 0 && p.sorted.every((c) => p.selected[c.id]);
  const header = (col: SortCol, label: string, num = false) => (
    <button type="button" className={`th${num ? ' num' : ''}`} onClick={() => p.onSort(col)}>
      {label}{arrow(col)}
    </button>
  );
  return (
    <div className="table-wrap">
      <div className="card table-card">
        <div className="trow thead">
          <div className="td-check" style={{ paddingTop: 9, paddingBottom: 9 }}>
            <Checkbox checked={allChecked} onToggle={p.onToggleAll} size={15} />
          </div>
          <div className="th">Claim ID</div>
          {header('payer', 'Payer')}
          <div className="th">CARC · Reason</div>
          {header('billed', 'Billed', true)}
          {header('denial', 'Denied')}
          {header('deadline', 'Deadline')}
          {header('days', 'Days Left')}
          <div className="th">Status</div>
        </div>
        {p.sorted.map((c) => (
          <div
            key={c.id}
            className={`trow tbody-row${p.selected[c.id] ? ' sel' : ''}`}
            onClick={() => p.onOpenClaim(c.id)}
          >
            <div className="td-check">
              <Checkbox
                checked={!!p.selected[c.id]}
                onToggle={(e) => { e.stopPropagation(); p.onToggleClaim(c.id); }}
                size={15}
              />
            </div>
            <div className="td td-id">{c.id}</div>
            <div className="td">{c.payer}</div>
            <div className="td td-carc">
              <span className="code">{c.carc}</span>
              <span className="why"> · {c.carcText ?? ''}</span>
            </div>
            <div className="td td-num">{fmtMoney(c.billed)}</div>
            <div className="td td-date">{fmtDate(c.denialDate)}</div>
            <div className="td td-date" style={{ color: 'var(--ink-2)' }}>{fmtDate(c.deadline)}</div>
            <div className="td"><DaysPill claim={c} /></div>
            <div className="td"><StatusPill status={effectiveStatus(c, p.statusOverrides)} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}
