import { useMemo, useState } from 'react';
import type { CarcMapping, CsvMappingSpec } from './api';

export const CANONICAL: { key: string; label: string; required: boolean }[] = [
  { key: 'claim_id', label: 'Claim ID', required: true },
  { key: 'payer', label: 'Payer', required: true },
  { key: 'carc_code', label: 'CARC code', required: true },
  { key: 'rarc_codes', label: 'RARC codes', required: false },
  { key: 'denial_reason_text', label: 'Denial reason text', required: false },
  { key: 'billed_amount', label: 'Billed amount', required: true },
  { key: 'service_date', label: 'Service date', required: true },
  { key: 'denial_date', label: 'Denial date', required: true },
  { key: 'appeal_deadline', label: 'Appeal deadline', required: false },
];

const SYNONYMS: Record<string, string[]> = {
  claim_id: ['claim id', 'claim number', 'claim no', 'claim', 'pcn',
    'patient control number', 'patient control no'],
  payer: ['payer', 'payer name', 'carrier', 'insurance', 'plan'],
  carc_code: ['carc', 'carc code', 'reason code', 'adj reason code',
    'adjustment reason code', 'denial code'],
  rarc_codes: ['rarc', 'rarc code', 'rarc codes', 'remark code', 'remark codes'],
  denial_reason_text: ['denial reason', 'reason', 'description', 'remark'],
  billed_amount: ['billed', 'billed amount', 'charge', 'charges',
    'charge amount', 'total charges'],
  service_date: ['service date', 'dos', 'date of service', 'from date'],
  denial_date: ['denial date', 'denied date', 'remit date',
    'remittance date', 'check date'],
  appeal_deadline: ['appeal deadline', 'appeal by', 'deadline', 'file by'],
};
const GROUP_SYNONYMS = ['group code', 'adj group', 'adjustment group', 'carc group'];

const norm = (h: string) =>
  h.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();

export function suggestMapping(headers: string[]): CsvMappingSpec {
  const byNorm = new Map(headers.map((h) => [norm(h), h]));
  const out: CsvMappingSpec = {};
  for (const { key } of CANONICAL) {
    for (const cand of [key, ...(SYNONYMS[key] ?? [])].map(norm)) {
      const hit = byNorm.get(cand);
      if (hit) { out[key] = hit; break; }
    }
  }
  const group = GROUP_SYNONYMS.map(norm).map((g) => byNorm.get(g)).find(Boolean);
  if (group && typeof out.carc_code === 'string') {
    out.carc_code = { group, code: out.carc_code };
  }
  return out;
}

export const headerKey = (headers: string[]) =>
  headers.map(norm).sort().join('\n');

interface Props {
  headers: string[];
  sampleRows: Record<string, string>[];
  defaultAppealDays: number;
  initial?: CsvMappingSpec;
  onConfirm: (mapping: CsvMappingSpec, remember: boolean) => void;
  onCancel: () => void;
}

const selectStyle = {
  font: 'inherit', fontSize: 12.5, padding: '5px 8px',
  border: '1px solid #DBD8D1', borderRadius: 6,
} as const;

export function MappingPanel(p: Props) {
  const suggestion = useMemo(
    () => p.initial ?? suggestMapping(p.headers), [p.headers, p.initial],
  );
  const initialCarc = suggestion.carc_code as CarcMapping | undefined;
  const [twoColCarc, setTwoColCarc] = useState(
    typeof initialCarc === 'object' && initialCarc !== null,
  );
  const [sel, setSel] = useState<Record<string, string>>(() => {
    const s: Record<string, string> = {};
    for (const { key } of CANONICAL) {
      const v = suggestion[key];
      if (typeof v === 'string') s[key] = v;
    }
    if (typeof initialCarc === 'object' && initialCarc !== null) {
      s.carc_code = initialCarc.code;
      s.carc_group = initialCarc.group;
    }
    return s;
  });
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState('');

  const sample = (header: string | undefined) =>
    header ? (p.sampleRows[0]?.[header] ?? '') : '';

  const confirm = () => {
    for (const { key, label, required } of CANONICAL) {
      if (required && key !== 'carc_code' && !sel[key]) {
        setError(`${label} is required`);
        return;
      }
    }
    if (!sel.carc_code || (twoColCarc && !sel.carc_group)) {
      setError('CARC code is required');
      return;
    }
    const mapping: CsvMappingSpec = {};
    for (const { key } of CANONICAL) {
      if (key === 'carc_code') continue;
      if (sel[key]) mapping[key] = sel[key];
    }
    mapping.carc_code = twoColCarc
      ? { group: sel.carc_group, code: sel.carc_code }
      : sel.carc_code;
    p.onConfirm(mapping, remember);
  };

  const fieldRow = (key: string, label: string, required: boolean) => (
    <div key={key} className="audit-row" style={{ gap: 12, alignItems: 'center' }}>
      <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
        {label}{required && <span style={{ color: 'var(--red-fg)' }}> *</span>}
        <select
          aria-label={label}
          value={sel[key] ?? ''}
          onChange={(e) => setSel((s) => ({ ...s, [key]: e.target.value }))}
          style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}
        >
          <option value="">(not present)</option>
          {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
      </label>
      <span style={{ fontFamily: 'var(--mono)', fontSize: 11.5,
                     color: 'var(--mut)', overflow: 'hidden',
                     textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {sample(sel[key])}
      </span>
    </div>
  );

  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <div className="panel-head">
        <div className="panel-title">Map your columns</div>
        <div className="panel-sub">{p.headers.length} columns detected</div>
      </div>
      <div style={{ marginTop: 8 }}>
        {CANONICAL.filter((f) => f.key !== 'carc_code' && f.key !== 'appeal_deadline')
          .map((f) => fieldRow(f.key, f.label, f.required))}

        <div className="audit-row" style={{ gap: 12, alignItems: 'center' }}>
          <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
            CARC code<span style={{ color: 'var(--red-fg)' }}> *</span>
            <select aria-label="CARC code" value={sel.carc_code ?? ''}
                    onChange={(e) => setSel((s) => ({ ...s, carc_code: e.target.value }))}
                    style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}>
              <option value="">(not present)</option>
              {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
          {twoColCarc && (
            <label style={{ flex: '0 0 180px', fontSize: 12.5, color: 'var(--ink-2)' }}>
              CARC group column
              <select aria-label="CARC group column" value={sel.carc_group ?? ''}
                      onChange={(e) => setSel((s) => ({ ...s, carc_group: e.target.value }))}
                      style={{ ...selectStyle, display: 'block', marginTop: 3, width: '100%' }}>
                <option value="">(not present)</option>
                {p.headers.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </label>
          )}
          <button type="button" className="btn"
                  onClick={() => setTwoColCarc((v) => !v)}>
            {twoColCarc ? 'Single column' : 'Group + code columns'}
          </button>
        </div>

        {fieldRow('appeal_deadline', 'Appeal deadline', false)}
        {!sel.appeal_deadline && (
          <div className="sm-note" style={{ marginTop: 4 }}>
            No deadline column — appeal deadline will be denial date + {p.defaultAppealDays} days
            (change in Org Settings).
          </div>
        )}
      </div>
      {error && <div style={{ fontSize: 12.5, color: 'var(--red-fg)', marginTop: 8 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
        <label style={{ fontSize: 12.5, color: 'var(--ink-2)', display: 'flex', gap: 6 }}>
          <input type="checkbox" checked={remember}
                 onChange={(e) => setRemember(e.target.checked)} />
          Remember this mapping
        </label>
        <div className="spacer" />
        <button type="button" className="btn" onClick={p.onCancel}>Cancel</button>
        <button type="button" className="btn-primary" onClick={confirm}>
          Use this mapping
        </button>
      </div>
    </div>
  );
}
