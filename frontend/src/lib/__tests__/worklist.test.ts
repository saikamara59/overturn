import { describe, expect, test } from 'vitest';
import type { Claim } from '../../types';
import { fmtDate, fmtMoney } from '../format';
import {
  bucketOf, daysChip, effectiveStatus, filterGroups, letterFileFor, statusStyle, visibleSorted,
} from '../worklist';

const claim = (over: Partial<Claim>): Claim => ({
  id: 'CLM-1', payer: 'P', carc: 'CO-50', carcText: 'desc', rarcs: [],
  billed: 100, dos: '2026-05-01', denialDate: '2026-06-01',
  deadline: '2026-08-01', days: 10, status: 'Draft Ready',
  denialText: 'text', letter: 'LETTER BODY', refined: 'REFINED',
  rule: 'rule', error: null, ...over,
});

describe('format', () => {
  test('fmtMoney formats cents and thousands', () => {
    expect(fmtMoney(1209224.78)).toBe('$1,209,224.78');
  });
  test('fmtDate shortens ISO and dashes null', () => {
    expect(fmtDate('2026-07-06')).toBe('07/06/26');
    expect(fmtDate(null)).toBe('—');
  });
});

describe('bucketOf', () => {
  test.each([
    [null, 'No deadline'], [-3, '<7 days'], [0, '<7 days'], [6, '<7 days'],
    [7, '7–30 days'], [29, '7–30 days'], [30, '30+ days'],
  ])('days=%s -> %s', (days, bucket) => {
    expect(bucketOf(claim({ days: days as number | null }))).toBe(bucket);
  });
});

describe('daysChip', () => {
  test('overdue is red with overdue label', () => {
    expect(daysChip(claim({ days: -5 }))).toEqual({ cls: 'c-red', label: '5d overdue' });
  });
  test('no deadline is gray dash', () => {
    expect(daysChip(claim({ days: null }))).toEqual({ cls: 'c-gray', label: '—' });
  });
  test('mid-range is amber', () => {
    expect(daysChip(claim({ days: 12 }))).toEqual({ cls: 'c-amber', label: '12d left' });
  });
});

describe('effectiveStatus', () => {
  test('override wins', () => {
    expect(effectiveStatus(claim({}), { 'CLM-1': 'Submitted' })).toBe('Submitted');
    expect(effectiveStatus(claim({}), {})).toBe('Draft Ready');
  });
});

describe('visibleSorted', () => {
  const claims = [
    claim({ id: 'A', days: 10, billed: 100, payer: 'Zeta' }),
    claim({ id: 'B', days: null, billed: 900, payer: 'Alpha' }),
    claim({ id: 'C', days: -2, billed: 50, payer: 'Mid', carc: 'CO-97' }),
    claim({ id: 'D', days: 10, billed: 500, payer: 'Mid2' }),
  ];
  const noFilters = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };

  test('default sort: urgency (days asc, billed desc), no-deadline last', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['C', 'D', 'A', 'B']);
  });
  test('billed desc sort', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'billed', dir: 'desc' }, {}).map(c => c.id);
    expect(ids).toEqual(['B', 'D', 'A', 'C']);
  });
  test('CARC filter narrows', () => {
    const ids = visibleSorted(claims, { ...noFilters, fCarc: ['CO-97'] }, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['C']);
  });
  test('bucket filter matches bucketOf', () => {
    const ids = visibleSorted(claims, { ...noFilters, fBucket: ['No deadline'] }, { col: 'urgency', dir: 'asc' }, {}).map(c => c.id);
    expect(ids).toEqual(['B']);
  });
});

describe('dismissed filtering', () => {
  const claims = [
    claim({ id: 'A', days: 5 }),
    claim({ id: 'B', days: 6 }),
  ];
  const noFilters = { fCarc: [], fPayer: [], fStatus: [], fBucket: [] };
  const overrides = { B: 'Dismissed' };

  test('dismissed hidden by default', () => {
    const ids = visibleSorted(claims, noFilters, { col: 'urgency', dir: 'asc' }, overrides).map(c => c.id);
    expect(ids).toEqual(['A']);
  });

  test('Dismissed status filter reveals them', () => {
    const ids = visibleSorted(claims, { ...noFilters, fStatus: ['Dismissed'] },
      { col: 'urgency', dir: 'asc' }, overrides).map(c => c.id);
    expect(ids).toEqual(['B']);
  });

  test('non-status filter counts exclude dismissed', () => {
    const groups = filterGroups(claims, overrides);
    const carc = groups.find(g => g.key === 'fCarc')!;
    expect(carc.items.find(i => i.label === 'CO-50')!.count).toBe(1);
    const status = groups.find(g => g.key === 'fStatus')!;
    expect(status.items.find(i => i.label === 'Dismissed')!.count).toBe(1);
  });

  test('statusStyle knows Dismissed', () => {
    expect(statusStyle('Dismissed').cls).toBe('c-gray');
  });
});

describe('letterFileFor', () => {
  test('assembles markdown with refined section', () => {
    const md = letterFileFor(claim({}));
    expect(md).toContain('# Appeal — claim CLM-1 (CO-50, P)');
    expect(md).toContain('LETTER BODY');
    expect(md).toContain('## Refined recommendation');
    expect(md).toContain('REFINED');
  });
  test('letter override replaces body', () => {
    expect(letterFileFor(claim({}), 'EDITED')).toContain('EDITED');
  });
});
