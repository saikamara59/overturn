import { filterGroups } from '../../lib/worklist';
import type { Claim, FilterKey, FilterState, StatusOverrides } from '../../types';

interface Props {
  claims: Claim[];
  filters: FilterState;
  onToggle: (key: FilterKey, val: string) => void;
  onReset: () => void;
  statusOverrides: StatusOverrides;
}

/** Mobile quick filters: deadline buckets then statuses, same filter state as the rail. */
export function MobileChips({ claims, filters, onToggle, onReset, statusOverrides }: Props) {
  const groups = filterGroups(claims, statusOverrides);
  const chips = (['fBucket', 'fStatus'] as FilterKey[]).flatMap((key) => {
    const g = groups.find((x) => x.key === key);
    return (g?.items ?? []).map((it) => ({ key, label: it.label }));
  });
  const anyFilters = Object.values(filters).some((a) => a.length > 0);
  return (
    <div className="chips">
      {anyFilters && (
        <button type="button" className="chip chip-reset" onClick={onReset}>Reset</button>
      )}
      {chips.map((c) => (
        <button
          type="button"
          key={`${c.key}:${c.label}`}
          className={`chip${filters[c.key].includes(c.label) ? ' on' : ''}`}
          aria-pressed={filters[c.key].includes(c.label)}
          onClick={() => onToggle(c.key, c.label)}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
