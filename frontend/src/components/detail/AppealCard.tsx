import { useRef, useState } from 'react';
import type { Claim } from '../../types';
import { MarkdownLite } from '../ui/MarkdownLite';

interface Props {
  claim: Claim;
  model: string | null;
  generatedOn: string | null;
  status: string;
  letter: string;
  onLetterChange: (text: string) => void;
  onApprove: () => void;
  onRevert: () => void;
  onExport: () => void;
  onDismiss?: (reason?: string) => void;
  onRestore?: () => void;
  onRegenerate?: () => void;
  dismissReason?: string;
}

export const REASON_LABELS: Record<string, string> = {
  payer_correct: 'payer was correct',
  too_small: 'amount too small',
  deadline_passed: 'deadline passed',
  other: 'other',
};

export function AppealCard(p: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showReason, setShowReason] = useState(false);
  const [reason, setReason] = useState('');
  const failed = p.status === 'Failed';
  const dismissed = p.status === 'Dismissed';
  const inFlight = p.status === 'Queued' || p.status === 'Drafting';
  const hasLetter = !!p.claim.letter;
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
      {dismissed && (
        <div className="fail-banner" style={{ background: 'var(--gray-bg)', borderColor: 'var(--line-2)' }}>
          <div className="t" style={{ color: 'var(--gray-fg)' }}>
            Dismissed — won't appeal{p.dismissReason ? ` (${REASON_LABELS[p.dismissReason] ?? p.dismissReason})` : ''}
          </div>
        </div>
      )}
      {inFlight ? (
        <div className="fail-banner" style={{ background: 'var(--blue-bg)', borderColor: 'var(--line-2)' }}>
          <div className="t" style={{ color: 'var(--blue-fg)' }}>Drafting in progress</div>
          <div className="b">
            This claim is queued for generation — the draft will appear here shortly.
          </div>
        </div>
      ) : failed || (dismissed && !hasLetter) ? (
        <div className="fail-banner">
          <div className="t">No appeal drafted</div>
          <div className="b">
            {p.claim.error ?? 'This record failed during batch processing.'}{' '}
            {p.onRegenerate
              ? 'Regenerate it below or write the appeal manually.'
              : 'Write the appeal manually or re-run the batch for this claim.'}
          </div>
        </div>
      ) : (
        <>
          <textarea
            ref={textareaRef}
            className="letter"
            spellCheck={false}
            value={p.letter}
            disabled={dismissed}
            onChange={(e) => { if (!dismissed) p.onLetterChange(e.target.value); }}
          />
          {p.claim.refined && (
            <div className="refined">
              <div className="t">Refined recommendation</div>
              <div className="b"><MarkdownLite text={p.claim.refined} /></div>
            </div>
          )}
        </>
      )}
      <div className="actions">
        {dismissed ? (
          p.onRestore && (
            <button type="button" className="btn-primary" onClick={p.onRestore}>Restore</button>
          )
        ) : inFlight ? (
          null
        ) : failed ? (
          <>
            {p.onRegenerate && (
              <button type="button" className="btn-primary" onClick={p.onRegenerate}>
                Regenerate
              </button>
            )}
            {p.onDismiss && !showReason && (
              <button type="button" className="btn" onClick={() => setShowReason(true)}>Dismiss</button>
            )}
          </>
        ) : (
          <>
            <button type="button" className="btn-primary" onClick={p.onApprove}>Approve</button>
            <button type="button" className="btn" onClick={() => textareaRef.current?.focus()}>Edit</button>
            <button type="button" className="btn" onClick={p.onRevert}>Revert draft</button>
            {p.onRegenerate && (
              <button type="button" className="btn" onClick={p.onRegenerate}>Regenerate</button>
            )}
            {p.onDismiss && !showReason && (
              <button type="button" className="btn" onClick={() => setShowReason(true)}>Dismiss</button>
            )}
          </>
        )}
        {showReason && !dismissed && (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 12.5, color: 'var(--mut)' }}>
              Reason
              <select value={reason} onChange={(e) => setReason(e.target.value)}
                      style={{ font: 'inherit', fontSize: 12.5, marginLeft: 6 }}>
                <option value="">(none)</option>
                {Object.entries(REASON_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <button type="button" className="btn"
                    onClick={() => { p.onDismiss?.(reason || undefined); setShowReason(false); }}>
              Confirm dismiss
            </button>
            <button type="button" className="btn" onClick={() => setShowReason(false)}>Cancel</button>
          </span>
        )}
        <div className="spacer" />
        {!failed && !dismissed && !inFlight && (
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
