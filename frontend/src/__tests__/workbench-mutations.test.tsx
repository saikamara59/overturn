import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import App, { type WorkbenchMutations } from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mutations(over: Partial<WorkbenchMutations> = {}): WorkbenchMutations {
  return {
    approve: vi.fn().mockResolvedValue(undefined),
    saveLetter: vi.fn().mockResolvedValue(undefined),
    revertLetter: vi.fn().mockResolvedValue('ORIGINAL FROM SERVER'),
    dismiss: vi.fn().mockResolvedValue({ status: 'Dismissed' }),
    restore: vi.fn().mockResolvedValue({ status: 'Draft Ready' }),
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

test('dismiss flow: button → reason picker → mutation → dismissed banner', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.selectOptions(screen.getByLabelText(/reason/i), 'too_small');
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  expect(m.dismiss).toHaveBeenCalledWith(expect.anything(), 'too_small');
  expect(await screen.findByText(/won't appeal/i)).toBeInTheDocument();
  // actions replaced by Restore; letter read-only
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toBeDisabled();
});

test('restore flow returns claim to worklist state', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  await userEvent.click(await screen.findByRole('button', { name: 'Restore' }));
  expect(m.restore).toHaveBeenCalledOnce();
  expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument();
});

test('bulk export skips a dismissed claim even when selected', async () => {
  const m = mutations();
  const { container } = render(<App data={SAMPLE_DATA} mutations={m} />);

  // dismiss CLM-0001 (it has a letter, so it would otherwise be exportable)
  await userEvent.click(screen.getByText('CLM-0001'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  await userEvent.click(screen.getByRole('button', { name: '← Worklist' }));

  // reveal every status, including Dismissed, so select-all can pick it up
  await userEvent.click(screen.getByRole('button', { name: /^Draft Ready/ }));
  await userEvent.click(screen.getByRole('button', { name: /^Failed/ }));
  await userEvent.click(screen.getByRole('button', { name: /^Dismissed/ }));

  const createObjectURL = vi.fn().mockReturnValue('blob:test');
  const revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

  const selectAll = container.querySelector('.thead .td-check button') as HTMLButtonElement;
  await userEvent.click(selectAll);

  await userEvent.click(screen.getByRole('button', { name: 'Export letters' }));

  // CLM-0001 (dismissed) and CLM-0004 (no letter) are excluded; only 2 export.
  expect(createObjectURL).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('status')).toHaveTextContent('2 letters exported');
});

test('dismissing a claim with no letter shows failure info and no textarea', async () => {
  const m = mutations();
  render(<App data={SAMPLE_DATA} mutations={m} />);
  await userEvent.click(screen.getByText('CLM-0004'));
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  await userEvent.click(screen.getByRole('button', { name: /confirm dismiss/i }));
  expect(await screen.findByText(/won't appeal/i)).toBeInTheDocument();
  expect(screen.getByText(/synthetic failure/)).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
});
