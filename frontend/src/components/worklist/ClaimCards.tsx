import { fmtDate, fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, StatusOverrides } from '../../types';
import { Checkbox } from '../ui/Checkbox';
import { DaysPill, StatusPill } from '../ui/Pills';

interface Props {
  sorted: Claim[];
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function ClaimCards(p: Props) {
  return (
    <div className="cards-wrap">
      {p.sorted.map((c) => (
        <div
          key={c.id}
          className={`claim-card${p.selected[c.id] ? ' sel' : ''}`}
          onClick={() => p.onOpenClaim(c.id)}
        >
          <div className="cc-top">
            <Checkbox
              checked={!!p.selected[c.id]}
              onToggle={(e) => { e.stopPropagation(); p.onToggleClaim(c.id); }}
              size={17}
            />
            <span className="cc-id">{c.id}</span>
            <span className="spacer" />
            <span className="cc-billed">{fmtMoney(c.billed)}</span>
          </div>
          <div className="cc-line">
            {c.payer} · <span className="code">{c.carc}</span> {c.carcText ?? ''}
          </div>
          <div className="cc-foot">
            <DaysPill claim={c} />
            <StatusPill status={effectiveStatus(c, p.statusOverrides)} />
            <span className="spacer" />
            <span className="cc-due">due {fmtDate(c.deadline)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
