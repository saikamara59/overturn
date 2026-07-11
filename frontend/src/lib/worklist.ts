import type { Claim, FilterState, SortState, StatusOverrides } from '../types';

export type Bucket = '<7 days' | '7–30 days' | '30+ days' | 'No deadline';
export const BUCKETS: Bucket[] = ['<7 days', '7–30 days', '30+ days', 'No deadline'];

export const effectiveStatus = (c: Claim, overrides: StatusOverrides): string =>
  overrides[c.id] ?? c.status;

export const bucketOf = (c: Claim): Bucket => {
  if (c.days === null) return 'No deadline';
  if (c.days < 7) return '<7 days';
  if (c.days < 30) return '7–30 days';
  return '30+ days';
};

export interface Chip { cls: string; label: string }

export const daysChip = (c: Claim): Chip => {
  if (c.days === null) return { cls: 'c-gray', label: '—' };
  if (c.days < 0) return { cls: 'c-red', label: `${-c.days}d overdue` };
  if (c.days < 7) return { cls: 'c-red', label: `${c.days}d left` };
  if (c.days < 30) return { cls: 'c-amber', label: `${c.days}d left` };
  return { cls: 'c-gray', label: `${c.days}d left` };
};

export const statusStyle = (s: string): { cls: string; dot: string } =>
  ({
    'Draft Ready': { cls: 'c-blue', dot: 'var(--blue-dot)' },
    'Needs Review': { cls: 'c-amber', dot: 'var(--amber-dot)' },
    Failed: { cls: 'c-red', dot: 'var(--red-dot)' },
    Submitted: { cls: 'c-green', dot: 'var(--green-dot)' },
    Dismissed: { cls: 'c-gray', dot: 'var(--gray-dot)' },
  })[s] ?? { cls: 'c-gray', dot: 'var(--gray-dot)' };

const daysValue = (c: Claim): number => (c.days === null ? Infinity : c.days);

export function visibleSorted(
  claims: Claim[],
  filters: FilterState,
  sort: SortState,
  overrides: StatusOverrides,
): Claim[] {
  const showDismissed = filters.fStatus.includes('Dismissed');
  const visible = claims.filter((c) => {
    const st = effectiveStatus(c, overrides);
    if (st === 'Dismissed' && !showDismissed) return false;
    return (
      (!filters.fCarc.length || filters.fCarc.includes(c.carc)) &&
      (!filters.fPayer.length || filters.fPayer.includes(c.payer)) &&
      (!filters.fStatus.length || filters.fStatus.includes(st)) &&
      (!filters.fBucket.length || filters.fBucket.includes(bucketOf(c)))
    );
  });
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...visible].sort((a, b) => {
    switch (sort.col) {
      case 'payer': return dir * a.payer.localeCompare(b.payer);
      case 'billed': return dir * (a.billed - b.billed);
      case 'denial': return dir * a.denialDate.localeCompare(b.denialDate);
      case 'deadline': return dir * String(a.deadline ?? '9999').localeCompare(String(b.deadline ?? '9999'));
      case 'days': return dir * (daysValue(a) - daysValue(b));
      default: return daysValue(a) - daysValue(b) || b.billed - a.billed;
    }
  });
}

export interface FilterGroup {
  key: keyof FilterState;
  title: string;
  items: { label: string; count: number }[];
}

export function filterGroups(claims: Claim[], overrides: StatusOverrides): FilterGroup[] {
  const active = claims.filter((c) => effectiveStatus(c, overrides) !== 'Dismissed');
  const count = (fn: (c: Claim) => boolean) => active.filter(fn).length;
  const uniq = (xs: string[]) => [...new Set(xs)];
  return [
    {
      key: 'fCarc', title: 'CARC group',
      items: uniq(claims.map((c) => c.carc)).map((v) => ({ label: v, count: count((c) => c.carc === v) })),
    },
    {
      key: 'fPayer', title: 'Payer',
      items: uniq(claims.map((c) => c.payer)).sort().map((v) => ({ label: v, count: count((c) => c.payer === v) })),
    },
    {
      key: 'fStatus', title: 'Status',
      items: uniq(claims.map((c) => effectiveStatus(c, overrides))).map((v) => ({
        label: v,
        count: claims.filter((c) => effectiveStatus(c, overrides) === v).length,
      })),
    },
    {
      key: 'fBucket', title: 'Deadline',
      items: BUCKETS.map((v) => ({ label: v, count: count((c) => bucketOf(c) === v) }))
        .filter((it) => it.count > 0),
    },
  ];
}

export function letterFileFor(c: Claim, letterOverride?: string): string {
  const letter = letterOverride ?? c.letter ?? '';
  let body = `# Appeal — claim ${c.id} (${c.carc}, ${c.payer})\n\n${letter}\n`;
  if (c.refined) body += `\n---\n\n## Refined recommendation\n\n${c.refined}\n`;
  return body;
}

export function downloadLetter(c: Claim, letterOverride?: string): void {
  const blob = new Blob([letterFileFor(c, letterOverride)], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${c.id}-appeal.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
