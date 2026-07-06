import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

test('summary shows stat cards, CARC bars, deadline buckets, audit trail', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));

  expect(screen.getByText('Records processed')).toBeInTheDocument();
  expect(screen.getByText('Dollars at stake by CARC group')).toBeInTheDocument();
  expect(screen.getByText(/from audit\.jsonl · 3 events/)).toBeInTheDocument();
  expect(screen.getByText('batch_started')).toBeInTheDocument();
  // Overdue bucket exists (CLM-0001 days=-6)
  expect(screen.getByText('Overdue')).toBeInTheDocument();
});

test('approving a claim moves it into Approved this session', async () => {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  await userEvent.click(screen.getByRole('button', { name: 'Batch Summary' }));
  const card = screen.getByText('Approved this session').parentElement!;
  expect(card).toHaveTextContent('1');
});
