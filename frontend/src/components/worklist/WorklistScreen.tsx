import { useIsMobile } from '../../lib/useIsMobile';
import type {
  Claim, FilterKey, FilterState, SortCol, SortState, StatusOverrides, WorkbenchData,
} from '../../types';
import { BulkBar } from './BulkBar';
import { ClaimCards } from './ClaimCards';
import { ClaimsTable } from './ClaimsTable';
import { FilterRail } from './FilterRail';
import { MobileChips } from './MobileChips';
import { StatsStrip } from './StatsStrip';

export interface WorklistProps {
  data: WorkbenchData;
  filters: FilterState;
  onToggleFilter: (key: FilterKey, val: string) => void;
  onResetFilters: () => void;
  sort: SortState;
  onSort: (col: SortCol) => void;
  sorted: Claim[];
  selected: Record<string, boolean>;
  onToggleClaim: (id: string) => void;
  onToggleAll: () => void;
  onClearSelection: () => void;
  onExportSelected: () => void;
  onOpenClaim: (id: string) => void;
  statusOverrides: StatusOverrides;
}

export function WorklistScreen(p: WorklistProps) {
  const isMobile = useIsMobile();
  const selIds = Object.keys(p.selected).filter((id) => p.selected[id]);
  const selSum = p.data.claims
    .filter((c) => selIds.includes(c.id))
    .reduce((t, c) => t + c.billed, 0);
  return (
    <div className="wl">
      {!isMobile && (
        <FilterRail
          claims={p.data.claims}
          filters={p.filters}
          onToggle={p.onToggleFilter}
          onReset={p.onResetFilters}
          statusOverrides={p.statusOverrides}
        />
      )}
      <div className="main">
        <StatsStrip data={p.data} shownCount={p.sorted.length} />
        {isMobile && (
          <MobileChips
            claims={p.data.claims}
            filters={p.filters}
            onToggle={p.onToggleFilter}
            onReset={p.onResetFilters}
            statusOverrides={p.statusOverrides}
          />
        )}
        {selIds.length > 0 && (
          <BulkBar
            count={selIds.length}
            total={selSum}
            onClear={p.onClearSelection}
            onExport={p.onExportSelected}
          />
        )}
        {isMobile ? (
          <ClaimCards
            sorted={p.sorted}
            selected={p.selected}
            onToggleClaim={p.onToggleClaim}
            onOpenClaim={p.onOpenClaim}
            statusOverrides={p.statusOverrides}
          />
        ) : (
          <ClaimsTable
            sorted={p.sorted}
            sort={p.sort}
            onSort={p.onSort}
            selected={p.selected}
            onToggleClaim={p.onToggleClaim}
            onToggleAll={p.onToggleAll}
            onOpenClaim={p.onOpenClaim}
            statusOverrides={p.statusOverrides}
          />
        )}
      </div>
    </div>
  );
}
