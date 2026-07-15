import { fmtMoney } from '../../lib/format';
import type { WorkbenchData } from '../../types';

export function StatsStrip({ data, shownCount }: { data: WorkbenchData; shownCount: number }) {
  const all = data.claims;
  const lt7 = all.filter((c) => c.days !== null && c.days < 7).length;
  const mid = all.filter((c) => c.days !== null && c.days >= 7 && c.days < 30).length;
  const g30 = all.filter((c) => c.days !== null && c.days >= 30).length;
  return (
    <div className="stats">
      <div>
        <div className="stat-label">Total at stake</div>
        <div className="stat-value">{fmtMoney(data.totalBilled)}</div>
      </div>
      <div>
        <div className="stat-label">Records</div>
        <div className="stat-value">{all.length} <small>denied claims</small></div>
      </div>
      <div>
        <div className="stat-label">Appeal deadlines</div>
        <div className="stat-pills">
          <span className="pill c-red">{lt7} · &lt;7d</span>
          <span className="pill c-amber">{mid} · 7–30d</span>
          <span className="pill c-gray">{g30} · 30d+</span>
        </div>
      </div>
      <div className="spacer" />
      <div className="stat-showing" style={{ textAlign: 'right' }}>
        <div className="stat-label">Showing</div>
        <div className="shown">
          {shownCount === all.length ? `all ${all.length} claims` : `${shownCount} of ${all.length} claims`}
        </div>
      </div>
    </div>
  );
}
