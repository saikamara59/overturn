interface Props {
  checked: boolean;
  onToggle: (e: React.MouseEvent) => void;
  size?: number;
}

export function Checkbox({ checked, onToggle, size = 14 }: Props) {
  return (
    <button
      type="button"
      className={`cbox${checked ? ' on' : ''}`}
      style={{ width: size, height: size }}
      onClick={onToggle}
    >
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF"
        strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </button>
  );
}
