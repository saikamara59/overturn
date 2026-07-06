import { useRef } from 'react';
import type { Claim } from '../../types';

interface Props {
  claim: Claim;
  model: string | null;
  generatedOn: string | null;
  failed: boolean;
  letter: string;
  onLetterChange: (text: string) => void;
  onApprove: () => void;
  onRevert: () => void;
  onExport: () => void;
}

export function AppealCard(p: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  return (
    <div className="card appeal-card">
      <div className="card-head">
        <div className="card-title">Drafted appeal</div>
        <div className="card-sub">editable draft — not sent</div>
      </div>
      <div className="meta-strip">
        <div>Model <b>{p.model ?? 'refinement skipped (dry run)'}</b></div>
        {p.claim.rule && <div>Cites <b>{p.claim.rule}</b></div>}
        <div>Generated <b>{p.generatedOn ?? '—'}</b></div>
      </div>
      {p.failed ? (
        <div className="fail-banner">
          <div className="t">No appeal drafted</div>
          <div className="b">
            {p.claim.error ?? 'This record failed during batch processing.'}{' '}
            Write the appeal manually or re-run the batch for this claim.
          </div>
        </div>
      ) : (
        <>
          <textarea
            ref={textareaRef}
            className="letter"
            spellCheck={false}
            value={p.letter}
            onChange={(e) => p.onLetterChange(e.target.value)}
          />
          {p.claim.refined && (
            <div className="refined">
              <div className="t">Refined recommendation</div>
              <div className="b">{p.claim.refined}</div>
            </div>
          )}
        </>
      )}
      <div className="actions">
        {!p.failed && (
          <>
            <button type="button" className="btn-primary" onClick={p.onApprove}>Approve</button>
            <button type="button" className="btn" onClick={() => textareaRef.current?.focus()}>Edit</button>
            <button type="button" className="btn" onClick={p.onRevert}>Revert draft</button>
          </>
        )}
        <div className="spacer" />
        {!p.failed && (
          <button type="button" className="btn" onClick={p.onExport}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export letter
          </button>
        )}
      </div>
    </div>
  );
}
