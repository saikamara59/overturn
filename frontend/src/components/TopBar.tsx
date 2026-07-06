import type { Screen } from '../types';

interface Props {
  screen: Screen;
  onNavigate: (s: Screen) => void;
  generatedOn: string | null;
  asOf: string | null;
}

export function TopBar({ screen, onNavigate, generatedOn, asOf }: Props) {
  const onSummary = screen === 'summary';
  return (
    <div className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
            strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 12a9 9 0 1 0 3-6.7" />
            <polyline points="3 4 3 9 8 9" />
          </svg>
        </div>
        <div className="brand-name">Overturn</div>
      </div>
      <div className="topbar-rule" />
      <div className="tabs">
        <button type="button" className={`tab${!onSummary ? ' on' : ''}`} onClick={() => onNavigate('worklist')}>
          Worklist
        </button>
        <button type="button" className={`tab${onSummary ? ' on' : ''}`} onClick={() => onNavigate('summary')}>
          Batch Summary
        </button>
      </div>
      <div className="spacer" />
      <div className="topbar-meta">
        worklist {generatedOn ?? '—'} · deadlines as of {asOf ?? '—'}
      </div>
    </div>
  );
}
