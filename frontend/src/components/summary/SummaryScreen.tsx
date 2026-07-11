import { fmtMoney } from '../../lib/format';
import { effectiveStatus } from '../../lib/worklist';
import type { Claim, StatusOverrides, WorkbenchData } from '../../types';

interface Props {
  data: WorkbenchData;
  statusOverrides: StatusOverrides;
  onBack: () => void;
}

const EVENT_CLS: Record<string, string> = {
  phi_redacted: 'c-green',
  appeal_generated: 'c-blue',
  recommendation_generated: 'c-blue',
  record_failed: 'c-red',
  generation_failed: 'c-red',
  batch_started: 'c-gray',
  batch_completed: 'c-gray',
};

interface BucketDef {
  label: string;
  cls: string;
  bar: string;
  test: (c: Claim) => boolean;
  always: boolean;
}

const BUCKET_DEFS: BucketDef[] = [
  { label: 'Overdue', cls: 'c-red', bar: 'var(--red-dot)', test: (c) => c.days !== null && c.days < 0, always: false },
  { label: '<7 days', cls: 'c-red', bar: 'var(--red-dot)', test: (c) => c.days !== null && c.days >= 0 && c.days < 7, always: true },
  { label: '7–30 days', cls: 'c-amber', bar: 'var(--amber-dot)', test: (c) => c.days !== null && c.days >= 7 && c.days < 30, always: true },
  { label: '30+ days', cls: 'c-gray', bar: 'var(--gray-dot)', test: (c) => c.days !== null && c.days >= 30, always: true },
  { label: 'No deadline', cls: 'c-gray', bar: 'var(--gray-dot)', test: (c) => c.days === null, always: false },
];

export function SummaryScreen({ data, statusOverrides, onBack }: Props) {
  const all = data.claims;
  const submitted = all.filter((c) => effectiveStatus(c, statusOverrides) === 'Submitted').length;

  const carcTotals = new Map<string, { amt: number; n: number }>();
  for (const c of all) {
    const t = carcTotals.get(c.carc) ?? { amt: 0, n: 0 };
    t.amt += c.billed; t.n += 1;
    carcTotals.set(c.carc, t);
  }
  const maxAmt = Math.max(1, ...[...carcTotals.values()].map((t) => t.amt));

  const buckets = BUCKET_DEFS
    .map((b) => ({ ...b, count: all.filter(b.test).length }))
    .filter((b) => b.always || b.count > 0);
  const maxB = Math.max(1, ...buckets.map((b) => b.count));

  const hot = all.filter((c) => c.days !== null && c.days < 7);
  const hotSum = hot.reduce((t, c) => t + c.billed, 0);

  return (
    <div className="sm"><div className="sm-inner">
      <div className="sm-head">
        <div className="sm-title">Batch summary</div>
        <div className="sm-meta">worklist {data.generatedOn ?? '—'} · deadlines as of {data.asOf ?? '—'}</div>
        <div className="spacer" />
        <button type="button" className="sm-back" onClick={onBack}>← Back to worklist</button>
      </div>
      <div className="sm-cards">
        <div className="sm-card">
          <div className="stat-label">Records processed</div>
          <div className="sm-num">{data.summary.processed}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Drafts ready</div>
          <div className="sm-num" style={{ color: 'var(--blue-fg)' }}>{data.summary.drafts - submitted}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Approved this session</div>
          <div className="sm-num" style={{ color: 'var(--green-fg)' }}>{submitted}</div>
        </div>
        <div className="sm-card">
          <div className="stat-label">Failed</div>
          <div className="sm-num" style={{ color: 'var(--red-fg)' }}>{data.summary.failed}</div>
        </div>
      </div>
      <div className="sm-grid">
        <div className="panel">
          <div className="panel-head">
            <div className="panel-title">Dollars at stake by CARC group</div>
            <div className="panel-sub">{fmtMoney(data.totalBilled)} total</div>
          </div>
          <div className="bars">
            {[...carcTotals.entries()].sort((a, b) => b[1].amt - a[1].amt).map(([code, t]) => (
              <div className="bar-row" key={code}>
                <div className="code">{code}</div>
                <div className="bar-track">
                  <div className="bar-fill" style={{ width: `${Math.max(2, Math.round((t.amt / maxAmt) * 100))}%` }} />
                </div>
                <div className="bar-amt">{fmtMoney(t.amt)}</div>
                <div className="bar-n">×{t.n}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="panel">
            <div className="panel-title">Deadline distribution</div>
            <div className="bars">
              {buckets.map((b) => (
                <div className="dl-row" key={b.label}>
                  <span className={`pill ${b.cls}`}>{b.label}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ background: b.bar, width: `${Math.round((b.count / maxB) * 100)}%` }} />
                  </div>
                  <div className="dl-count">{b.count}</div>
                </div>
              ))}
            </div>
            {hot.length > 0 && (
              <div className="sm-note">
                {hot.length} claim{hot.length === 1 ? '' : 's'} worth <b>{fmtMoney(hotSum)}</b>{' '}
                expire{hot.length === 1 ? 's' : ''} within 7 days.
              </div>
            )}
            {(data.summary.dismissed ?? 0) > 0 && (
              <div className="sm-note">
                {data.summary.dismissed} dismissed (won't appeal).
              </div>
            )}
          </div>
          <div className="panel">
            <div className="panel-head">
              <div className="panel-title">Audit trail</div>
              <div className="card-sub">from audit.jsonl · {data.audit.length} events</div>
            </div>
            <div className="audit-list">
              {data.audit.length === 0 && (
                <div className="sm-note">No audit.jsonl found next to worklist.json.</div>
              )}
              {data.audit.map((e, i) => (
                <div className="audit-row" key={i}>
                  <div className="audit-time">{e.time}</div>
                  <div className={`audit-type ${EVENT_CLS[e.type] ?? 'c-gray'}`}>{e.type}</div>
                  <div className="audit-detail">{e.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div></div>
  );
}
