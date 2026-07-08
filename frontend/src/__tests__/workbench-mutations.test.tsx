import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import App, { type WorkbenchMutations } from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

afterEach(() => {
  vi.useRealTimers();
});

function mutations(over: Partial<WorkbenchMutations> = {}): WorkbenchMutations {
  return {
    approve: vi.fn().mockResolvedValue(undefined),
    saveLetter: vi.fn().mockResolvedValue(undefined),
    revertLetter: vi.fn().mockResolvedValue('ORIGINAL FROM SERVER'),
    ...over,
  };
}

test('approve awaits server then marks Submitted', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(m.approve).toHaveBeenCalledOnce();
  expect(await screen.findByText('Submitted')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('saved');
});

test('letter edits debounce a saveLetter call', async () => {
  const user = userEvent.setup();
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await user.click(screen.getByText('CLM-0001'));

  const textbox = screen.getByRole('textbox');
  await user.clear(textbox);
  await user.type(textbox, 'X');

  expect(m.saveLetter).not.toHaveBeenCalled();

  // Wait for debounce to fire (800ms configured in App.tsx)
  await new Promise(resolve => setTimeout(resolve, 900));

  expect(m.saveLetter).toHaveBeenCalledOnce();
});

test('revert uses server-restored letter', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Revert draft' }));
  expect(m.revertLetter).toHaveBeenCalledOnce();
  expect(
    await screen.findByDisplayValue('ORIGINAL FROM SERVER'),
  ).toBeInTheDocument();
});

test('approve failure shows error toast and keeps status', async () => {
  const m = mutations({ approve: vi.fn().mockRejectedValue(new Error('offline')) });
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(await screen.findByRole('status')).toHaveTextContent('offline');
  expect(screen.queryByText('Submitted')).not.toBeInTheDocument();
});
