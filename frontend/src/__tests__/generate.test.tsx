import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import App, { type WorkbenchMutations } from '../App';
import { BulkBar } from '../components/worklist/BulkBar';
import { statusStyle } from '../lib/worklist';
import { makeData } from './helpers/data';

function mutationsWith(generate: WorkbenchMutations['generate']): WorkbenchMutations {
  return {
    approve: vi.fn(), saveLetter: vi.fn(), revertLetter: vi.fn(),
    dismiss: vi.fn(), restore: vi.fn(), generate,
  };
}

test('BulkBar shows Generate Appeals only when a handler is provided', () => {
  const { rerender } = render(
    <BulkBar count={1} total={100} onClear={vi.fn()} onExport={vi.fn()} />,
  );
  expect(screen.queryByRole('button', { name: 'Generate Appeals' })).toBeNull();
  rerender(
    <BulkBar count={1} total={100} onClear={vi.fn()} onExport={vi.fn()}
      onGenerate={vi.fn()} />,
  );
  expect(screen.getByRole('button', { name: 'Generate Appeals' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Export letters' })).toBeInTheDocument();
});

test('selecting a claim and clicking Generate Appeals calls the mutation and toasts', async () => {
  const data = makeData();
  const generate = vi.fn().mockResolvedValue({ queued: 1, skipped: 0 });
  render(<App data={data} mutations={mutationsWith(generate)} />);

  fireEvent.click(document.querySelectorAll('.tbody-row .cbox')[0] as HTMLElement);
  fireEvent.click(screen.getByRole('button', { name: 'Generate Appeals' }));

  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
  expect(generate.mock.calls[0][0]).toHaveLength(1);
  await screen.findByText(/Appeal generation queued for 1 claim/);
});

test('skipped claims are reported in the toast', async () => {
  const data = makeData();
  const generate = vi.fn().mockResolvedValue({ queued: 1, skipped: 2 });
  render(<App data={data} mutations={mutationsWith(generate)} />);
  fireEvent.click(document.querySelector('.thead .cbox') as HTMLElement); // select all
  fireEvent.click(screen.getByRole('button', { name: 'Generate Appeals' }));
  await screen.findByText(/queued for 1 claim · 2 skipped/);
});

test('without mutations the bulk bar keeps Export as the only action', () => {
  const data = makeData();
  render(<App data={data} />);
  fireEvent.click(document.querySelectorAll('.tbody-row .cbox')[0] as HTMLElement);
  expect(screen.queryByRole('button', { name: 'Generate Appeals' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Export letters' })).toBeInTheDocument();
});

test('statusStyle covers the in-flight statuses', () => {
  expect(statusStyle('Queued').cls).toBe('c-gray');
  expect(statusStyle('Drafting').cls).toBe('c-amber');
});
