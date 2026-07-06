import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect } from 'vitest';
import App from '../App';
import { SAMPLE_DATA } from '../fixtures/sample';

async function openClaim(id: string) {
  render(<App data={SAMPLE_DATA} />);
  await userEvent.click(screen.getByText(id));
}

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
