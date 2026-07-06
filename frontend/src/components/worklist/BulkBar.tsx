import { fmtMoney } from '../../lib/format';

interface Props {
  count: number;
  total: number;
  onClear: () => void;
  onExport: () => void;
}

export function BulkBar({ count, total, onClear, onExport }: Props) {
  return (
    <div className="bulk">
      <div className="bulk-label">{count} claim{count === 1 ? '' : 's'} selected</div>
      <div className="bulk-value">{fmtMoney(total)} at stake</div>
      <div className="spacer" />
      <button type="button" className="bulk-clear" onClick={onClear}>Clear</button>
      <button type="button" className="btn-primary" onClick={onExport}>Export letters</button>
    </div>
  );
}
