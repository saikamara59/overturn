import { fmtMoney } from '../../lib/format';

interface Props {
  count: number;
  total: number;
  onClear: () => void;
  onExport: () => void;
  onGenerate?: () => void;
}

export function BulkBar({ count, total, onClear, onExport, onGenerate }: Props) {
  return (
    <div className="bulk">
      <div className="bulk-label">{count} claim{count === 1 ? '' : 's'} selected</div>
      <div className="bulk-value">{fmtMoney(total)} at stake</div>
      <div className="spacer" />
      <button type="button" className="bulk-clear" onClick={onClear}>Clear</button>
      {onGenerate ? (
        <>
          <button type="button" className="btn" onClick={onExport}>Export letters</button>
          <button type="button" className="btn-primary" onClick={onGenerate}>
            Generate Appeals
          </button>
        </>
      ) : (
        <button type="button" className="btn-primary" onClick={onExport}>
          Export letters
        </button>
      )}
    </div>
  );
}
