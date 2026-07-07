import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

test('renders stats, rows in urgency order, filters narrow, selection shows bulk bar', async () => {
  render(<App data={SAMPLE_DATA} />);

  expect(screen.getByText('$60,920.25')).toBeInTheDocument();
  expect(screen.getByText('all 4 claims')).toBeInTheDocument();

  // urgency order: overdue first, no-deadline last
  const ids = screen.getAllByText(/^CLM-\d+$/).map((el) => el.textContent);
  expect(ids).toEqual(['CLM-0001', 'CLM-0002', 'CLM-0004', 'CLM-0003']);

  // filter: CO-50 narrows to 1 of 4
  await userEvent.click(screen.getByRole('button', { name: /CO-50/ }));
  expect(screen.getByText('1 of 4 claims')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Reset' }));
  expect(screen.getByText('all 4 claims')).toBeInTheDocument();

  // selection: row checkbox -> bulk bar
  const row = screen.getByText('CLM-0001').closest('.tbody-row')!;
  await userEvent.click(within(row as HTMLElement).getByRole('button'));
  expect(screen.getByText('1 claim selected')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect(screen.queryByText('1 claim selected')).not.toBeInTheDocument();
});

test('sort by billed toggles direction', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByRole('button', { name: /Billed/ }));
  const ids = screen.getAllByText(/^CLM-\d+$/).map((el) => el.textContent);
  expect(ids[0]).toBe('CLM-0004'); // largest billed first (desc default)
});
