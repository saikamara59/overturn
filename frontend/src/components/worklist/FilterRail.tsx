import { filterGroups } from '../../lib/worklist';
import type { Claim, FilterKey, FilterState, StatusOverrides } from '../../types';

interface Props {
  claims: Claim[];
  filters: FilterState;
  onToggle: (key: FilterKey, val: string) => void;
  onReset: () => void;
  statusOverrides: StatusOverrides;
}

export function FilterRail({ claims, filters, onToggle, onReset, statusOverrides }: Props) {
  const anyFilters = Object.values(filters).some((a) => a.length > 0);
  return (
    <div className="rail">
      <div className="rail-head">
        <div className="rail-title">Filters</div>
        {anyFilters && (
          <button type="button" className="rail-reset" onClick={onReset}>Reset</button>
        )}
      </div>
      {filterGroups(claims, statusOverrides).map((g) => (
        <div className="fgroup" key={g.key}>
          <div className="fgroup-title">{g.title}</div>
          {g.items.map((it) => (
            <button
              type="button"
              className="fitem"
              key={it.label}
              onClick={() => onToggle(g.key, it.label)}
            >
              <span className={`cbox${filters[g.key].includes(it.label) ? ' on' : ''}`}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
                  strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
              <span className="fitem-label">{it.label}</span>
              <span className="fitem-count">{it.count}</span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}
