import { daysChip, statusStyle } from '../../lib/worklist';
import type { Claim } from '../../types';

export function DaysPill({ claim }: { claim: Claim }) {
  const chip = daysChip(claim);
  return <span className={`pill ${chip.cls}`}>{chip.label}</span>;
}

export function StatusPill({ status }: { status: string }) {
  const st = statusStyle(status);
  return (
    <span className={`st ${st.cls}`}>
      <span className="dot" style={{ background: st.dot }} />
      {status}
    </span>
  );
}
