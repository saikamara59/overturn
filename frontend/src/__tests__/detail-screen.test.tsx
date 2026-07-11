import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, test, expect, vi } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

async function openClaim(id: string) {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByText(id));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('detail shows denial fields, PHI chips, letter, and approve flow', async () => {
  await openClaim('CLM-0001');

  expect(screen.getByText('parsed from 835 remittance')).toBeInTheDocument();
  expect(screen.getByText('N115')).toBeInTheDocument();
  expect(screen.getByText('PHI redacted before model call')).toBeInTheDocument();
  // [PATIENT_NAME] in denial text renders as a chip without brackets
  expect(screen.getAllByText('PATIENT_NAME').length).toBeGreaterThan(0);

  const textarea = screen.getByRole('textbox');
  expect((textarea as HTMLTextAreaElement).value).toContain('Formal Appeal');

  await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(screen.getByText('Submitted')).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('approved');
});

test('editing then reverting restores the generated letter', async () => {
  await openClaim('CLM-0001');
  const textarea = screen.getByRole('textbox');
  await userEvent.clear(textarea);
  await userEvent.type(textarea, 'edited');
  expect(textarea).toHaveValue('edited');
  await userEvent.click(screen.getByRole('button', { name: 'Revert draft' }));
  expect(screen.getByRole('textbox')).not.toHaveValue('edited');
});

test('failed claim shows banner and no letter actions', async () => {
  await openClaim('CLM-0004');
  expect(screen.getByText('No appeal drafted')).toBeInTheDocument();
  expect(screen.getByText(/synthetic failure/)).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
});

test('export triggers a download', async () => {
  await openClaim('CLM-0001');

  const createObjectURL = vi.fn().mockReturnValue('blob:test');
  const revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
  const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

  // Use fake timers + fireEvent (not userEvent) so downloadLetter's deferred
  // revokeObjectURL setTimeout never escapes as a pending real-clock timer.
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: 'Export letter' }));

  expect(createObjectURL).toHaveBeenCalledTimes(1);
  expect(createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
  expect(clickSpy).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('status')).toHaveTextContent('Exported CLM-0001-appeal.md');

  act(() => {
    vi.advanceTimersByTime(5000);
  });
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:test');

  clickSpy.mockRestore();
});

test('island mode shows no Dismiss button', async () => {
  await openClaim('CLM-0001');
  expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument();
});
