import { Fragment } from 'react';
import { fmtDate, fmtMoney } from '../../lib/format';
import type { Claim } from '../../types';

function PhiText({ text }: { text: string }) {
  const parts = text.split(/(\[[A-Z_]+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[[A-Z_]+\]$/.test(p)
          ? <span className="phi-tag" key={i}>{p.slice(1, -1)}</span>
          : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  );
}

export function DenialCard({ claim }: { claim: Claim }) {
  const hot = claim.days !== null && claim.days < 7;
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">Denial</div>
        <div className="card-sub">parsed from 835 remittance</div>
      </div>
      <div className="kv">
        <div className="k">Payer</div><div className="v">{claim.payer}</div>
        <div className="k">Date of service</div><div className="v mono">{fmtDate(claim.dos)}</div>
        <div className="k">Billed</div><div className="v mono">{fmtMoney(claim.billed)}</div>
        <div className="k">Denial date</div><div className="v mono">{fmtDate(claim.denialDate)}</div>
        <div className="k">Appeal deadline</div>
        <div className="v mono" style={{ fontWeight: 600, color: hot ? 'var(--red-fg)' : 'var(--ink)' }}>
          {fmtDate(claim.deadline)}
        </div>
      </div>
      <div className="codes">
        <div className="k" style={{ color: 'var(--mut)', fontSize: '12.5px' }}>CARC</div>
        <div>
          <span className="code-chip">{claim.carc}</span>
          <div className="code-text">
            {claim.carcText ?? 'Code not in the curated CARC database — fallback appeal grounds were used.'}
          </div>
        </div>
        <div className="k" style={{ color: 'var(--mut)', fontSize: '12.5px' }}>RARC</div>
        <div>
          {claim.rarcs.length
            ? claim.rarcs.map((r) => <span className="code-chip" key={r}>{r}</span>)
            : <span style={{ fontSize: '12.5px', color: 'var(--mut-2)' }}>none on remittance</span>}
        </div>
      </div>
      <div className="denial-block">
        <div className="denial-label">
          <b>Original denial text</b>
          <span className="phi-badge">
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#1F6B3D"
              strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            PHI redacted before model call
          </span>
        </div>
        <div className="denial-text"><PhiText text={claim.denialText} /></div>
      </div>
    </div>
  );
}
