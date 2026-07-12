import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { RunsScreen } from '../app/RunsScreen';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);
afterEach(() => fetchMock.mockReset());
const ok = (b: unknown, s = 200) => Promise.resolve(new Response(JSON.stringify(b), { status: s }));

const MESSY_CSV = `Claim Number,Carrier,Adj Group,Reason Code,Remark Codes,Denial Reason,Total Charges,DOS,Check Date
CLM-1,Acme Ins,CO,50,N115,Not medically necessary,"$12,500.00",04/10/2026,05/01/2026
`;

const MESSY_HEADERS = ['Claim Number', 'Carrier', 'Adj Group', 'Reason Code',
  'Remark Codes', 'Denial Reason', 'Total Charges', 'DOS', 'Check Date'];

function wire() {
  let savedMappings: unknown[] = [];
  let runs: unknown[] = [];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url === '/api/v1/org') {
      return ok({
        id: 'o1', name: 'Acme RCM', role: 'admin',
        hasApiKey: false, apiKeyLast4: null, defaultAppealDays: 90,
      });
    }
    if (url === '/api/v1/org/csv-mappings' && !init?.method) return ok(savedMappings);
    if (url === '/api/v1/runs' && !init?.method) return ok(runs);
    if (url === '/api/v1/runs' && init?.method === 'POST') {
      const body = init.body as FormData;
      const mapping = body.get('mapping');
      const saveMapping = body.get('save_mapping');
      if (mapping && saveMapping === 'true') {
        savedMappings = [{
          id: 'm1', name: 'Mapping (9 columns)', headers: MESSY_HEADERS,
          mapping: JSON.parse(mapping as string), lastUsedAt: '2026-07-12',
        }];
      }
      runs = [{
        id: 'r1', filename: 'waystar-export.csv', dryRun: true, isDemo: false,
        status: 'completed', totalRecords: 1, drafted: 1, failedRecords: 0,
        totalBilled: 12500, error: null,
        createdAt: '2026-07-12', startedAt: '2026-07-12', finishedAt: '2026-07-12',
      }];
      return ok({ runId: 'r1' });
    }
    return ok({}, 404);
  });
}

test('a same-session re-upload of the same header shape auto-applies the just-saved mapping', async () => {
  wire();
  const { container } = render(<RunsScreen onOpenRun={() => {}} />);

  const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File([MESSY_CSV], 'waystar-export.csv', { type: 'text/csv' });

  // first upload: no saved mapping yet, so the mapping panel should appear
  await userEvent.upload(fileInput, file);
  await screen.findByText('Map your columns');

  // confirm the suggested mapping with "remember this mapping" left on (default)
  await userEvent.click(screen.getByRole('button', { name: /use this mapping/i }));

  // jsdom doesn't mark a `required` file input as valid after userEvent.upload,
  // so a synthetic button click gets silently blocked by native constraint
  // validation (unlike real browsers/Playwright) — submit the form directly.
  fireEvent.submit(container.querySelector('form') as HTMLFormElement);

  // wait for the save-mapping upload to complete (run appears, saved mapping persisted server-side)
  await screen.findByText('waystar-export.csv');
  await waitFor(() => expect(fetchMock.mock.calls.filter(
    ([url, init]) => url === '/api/v1/org/csv-mappings' && !(init as RequestInit)?.method,
  ).length).toBeGreaterThan(1));

  // stage the identical-shape file again in the same session
  await userEvent.upload(fileInput, file);

  // should auto-apply the mapping just saved — badge, not the panel
  await screen.findByText(/using saved mapping/i);
  expect(screen.queryByText('Map your columns')).not.toBeInTheDocument();
});
