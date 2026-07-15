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
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M20 12a8 8 0 1 1-3.2-6.4" stroke="#FFFFFF"
              strokeWidth="3" strokeLinecap="round" />
            <path d="M17.4 1.6 L16.8 7.3 L22.3 6.1 Z" fill="#FFFFFF" />
          </svg>
        </div>
        <div className="brand-text">
          <div className="brand-name">Overturn<span className="brand-dot">.</span></div>
          <div className="brand-sub">Denial Workbench</div>
        </div>
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
