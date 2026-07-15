import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { WorklistScreen, type WorklistProps } from '../components/worklist/WorklistScreen';
import { NO_FILTERS } from '../types';
import { makeData } from './helpers/data';
import { resetViewport, setViewportMobile } from './helpers/matchMedia';

afterEach(() => resetViewport());

function props(overrides: Partial<WorklistProps> = {}): WorklistProps {
  const data = makeData();
  return {
    data,
    filters: NO_FILTERS,
    onToggleFilter: vi.fn(),
    onResetFilters: vi.fn(),
    sort: { col: 'urgency', dir: 'asc' },
    onSort: vi.fn(),
    sorted: data.claims,
    selected: {},
    onToggleClaim: vi.fn(),
    onToggleAll: vi.fn(),
    onClearSelection: vi.fn(),
    onExportSelected: vi.fn(),
    onOpenClaim: vi.fn(),
    statusOverrides: {},
    ...overrides,
  };
}

test('desktop shows rail + table, no chips or cards', () => {
  render(<WorklistScreen {...props()} />);
  expect(document.querySelector('.rail')).not.toBeNull();
  expect(document.querySelector('.table-card')).not.toBeNull();
  expect(document.querySelector('.chips')).toBeNull();
  expect(document.querySelector('.claim-card')).toBeNull();
  expect(document.querySelector('.stat-showing')).not.toBeNull();
});

test('mobile shows chips + cards, no rail or table', () => {
  setViewportMobile(true);
  render(<WorklistScreen {...props()} />);
  expect(document.querySelector('.rail')).toBeNull();
  expect(document.querySelector('.table-card')).toBeNull();
  expect(document.querySelector('.chips')).not.toBeNull();
  expect(document.querySelectorAll('.claim-card').length).toBeGreaterThan(0);
});

test('chips toggle bucket and status filters', () => {
  setViewportMobile(true);
  const p = props();
  render(<WorklistScreen {...p} />);
  fireEvent.click(screen.getByRole('button', { name: '<7 days' }));
  expect(p.onToggleFilter).toHaveBeenCalledWith('fBucket', '<7 days');
  fireEvent.click(screen.getByRole('button', { name: 'Draft Ready' }));
  expect(p.onToggleFilter).toHaveBeenCalledWith('fStatus', 'Draft Ready');
});

test('a Reset chip appears only when a filter is active', () => {
  setViewportMobile(true);
  const p = props({ filters: { ...NO_FILTERS, fPayer: ['Payer A'] } });
  render(<WorklistScreen {...p} />);
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
  expect(p.onResetFilters).toHaveBeenCalled();
});

test('card opens the claim; its checkbox selects without opening', () => {
  setViewportMobile(true);
  const p = props();
  render(<WorklistScreen {...p} />);
  const card = document.querySelector('.claim-card') as HTMLElement;
  fireEvent.click(card);
  expect(p.onOpenClaim).toHaveBeenCalled();
  const box = card.querySelector('.cbox') as HTMLElement;
  fireEvent.click(box);
  expect(p.onToggleClaim).toHaveBeenCalledTimes(1);
  expect(p.onOpenClaim).toHaveBeenCalledTimes(1); // stopPropagation held
});
