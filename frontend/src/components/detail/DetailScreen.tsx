import { fmtMoney } from '../../lib/format';
import type { Claim } from '../../types';
import { DaysPill, StatusPill } from '../ui/Pills';
import { AppealCard } from './AppealCard';
import { DenialCard } from './DenialCard';

interface Props {
  claim: Claim;
  status: string;
  model: string | null;
  generatedOn: string | null;
  letter: string;
  onBack: () => void;
  onLetterChange: (text: string) => void;
  onApprove: () => void;
  onRevert: () => void;
  onExport: () => void;
}

export function DetailScreen(p: Props) {
  return (
    <div className="detail">
      <button type="button" className="backlink" onClick={p.onBack}>← Worklist</button>
      <div className="d-head">
        <div className="d-id">{p.claim.id}</div>
        <StatusPill status={p.status} />
        <div className="d-payer">{p.claim.payer}</div>
        <DaysPill claim={p.claim} />
        <div className="spacer" />
        <div className="d-billed">{fmtMoney(p.claim.billed)}</div>
      </div>
      <div className="d-grid">
        <DenialCard claim={p.claim} />
        <AppealCard
          claim={p.claim}
          model={p.model}
          generatedOn={p.generatedOn}
          failed={p.status === 'Failed'}
          letter={p.letter}
          onLetterChange={p.onLetterChange}
          onApprove={p.onApprove}
          onRevert={p.onRevert}
          onExport={p.onExport}
        />
      </div>
    </div>
  );
}
