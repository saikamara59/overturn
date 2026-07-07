import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect, vi } from 'vitest';
import { TopBar } from '../components/TopBar';
import { Checkbox } from '../components/ui/Checkbox';
import { DaysPill, StatusPill } from '../components/ui/Pills';
import { Toast } from '../components/ui/Toast';
import type { Claim } from '../types';

const claim = { days: -4 } as Claim;

test('DaysPill shows overdue in red', () => {
  render(<DaysPill claim={claim} />);
  const pill = screen.getByText('4d overdue');
  expect(pill).toHaveClass('c-red');
});

test('StatusPill renders label with status class', () => {
  render(<StatusPill status="Submitted" />);
  expect(screen.getByText('Submitted')).toHaveClass('c-green');
});

test('Checkbox toggles', async () => {
  const onToggle = vi.fn();
  render(<Checkbox checked={false} onToggle={onToggle} />);
  await userEvent.click(screen.getByRole('button'));
  expect(onToggle).toHaveBeenCalledOnce();
});

test('Toast hides when empty', () => {
  const { rerender } = render(<Toast message="" />);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  rerender(<Toast message="Saved" />);
  expect(screen.getByRole('status')).toHaveTextContent('Saved');
});

test('TopBar navigates', async () => {
  const onNavigate = vi.fn();
  render(<TopBar screen="worklist" onNavigate={onNavigate} generatedOn="2026-07-06" asOf="2026-07-06" />);
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));
  expect(onNavigate).toHaveBeenCalledWith('summary');
});
