import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MappingPanel, suggestMapping } from '../app/MappingPanel';

const HEADERS = ['Claim Number', 'Carrier', 'Adj Group', 'Reason Code',
  'Remark Codes', 'Denial Reason', 'Total Charges', 'DOS', 'Check Date'];
const SAMPLE = [{
  'Claim Number': 'CLM-9001', Carrier: 'Acme Ins', 'Adj Group': 'CO',
  'Reason Code': '50', 'Remark Codes': 'N115',
  'Denial Reason': 'Not medically necessary',
  'Total Charges': '$12,500.00', DOS: '04/10/2026', 'Check Date': '05/01/2026',
}];

test('suggestMapping mirrors the server synonym table', () => {
  const s = suggestMapping(HEADERS);
  expect(s.claim_id).toBe('Claim Number');
  expect(s.carc_code).toEqual({ group: 'Adj Group', code: 'Reason Code' });
  expect(s.denial_date).toBe('Check Date');
  expect(s.appeal_deadline).toBeUndefined();
});

test('panel pre-selects suggestions, shows samples and deadline note, confirms', async () => {
  const onConfirm = vi.fn();
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={onConfirm} onCancel={() => {}} />);
  expect(screen.getByLabelText(/claim id/i)).toHaveValue('Claim Number');
  expect(screen.getByText('CLM-9001')).toBeInTheDocument();      // sample value
  expect(screen.getByText(/denial date \+ 90 days/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /use this mapping/i }));
  expect(onConfirm).toHaveBeenCalledOnce();
  const [mapping, remember] = onConfirm.mock.calls[0];
  expect(mapping.claim_id).toBe('Claim Number');
  expect(remember).toBe(true);                                    // default on
});

test('missing required selection blocks confirm', async () => {
  const onConfirm = vi.fn();
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={onConfirm} onCancel={() => {}} />);
  await userEvent.selectOptions(screen.getByLabelText(/payer/i), '');
  await userEvent.click(screen.getByRole('button', { name: /use this mapping/i }));
  expect(onConfirm).not.toHaveBeenCalled();
  expect(screen.getByText(/payer is required/i)).toBeInTheDocument();
});

test('carc toggle switches between single and group+code', async () => {
  render(<MappingPanel headers={HEADERS} sampleRows={SAMPLE}
                       defaultAppealDays={90}
                       onConfirm={() => {}} onCancel={() => {}} />);
  // auto-detected two-column mode: both selects present
  expect(screen.getByLabelText(/carc group column/i)).toHaveValue('Adj Group');
  await userEvent.click(screen.getByRole('button', { name: /single column/i }));
  expect(screen.queryByLabelText(/carc group column/i)).not.toBeInTheDocument();
});
