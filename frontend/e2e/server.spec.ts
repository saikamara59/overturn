import { expect, test } from '@playwright/test';

const CSV = `claim_id,payer,carc_code,rarc_codes,denial_reason_text,billed_amount,service_date,denial_date,appeal_deadline
CLM-E2E-1,Synthetic Payer A,CO-50,N115,These are non-covered services because this is not deemed a medical necessity.,12500.00,2026-04-10,2026-05-01,2026-08-30
CLM-E2E-2,Synthetic Payer B,CO-29,N30,The time limit for filing has expired.,430.25,2026-03-02,2026-04-15,2026-09-15
`;

test('upload → draft → approve → persists across reload', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  await page.setInputFiles('input[type=file]', {
    name: 'e2e-denials.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV),
  });
  await page.getByRole('button', { name: /upload/i }).click();

  const row = page.locator('.audit-row', { hasText: 'e2e-denials.csv' }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });

  await row.click();
  await expect(page.getByText('CLM-E2E-1')).toBeVisible();
  await page.getByText('CLM-E2E-1').click();
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('Submitted').first()).toBeVisible();

  await page.getByRole('button', { name: 'Batch Summary' }).click();
  await expect(page.getByText('Audit trail')).toBeVisible();

  await page.reload();
  await page.getByText('CLM-E2E-1').click();
  await expect(page.getByText('Submitted').first()).toBeVisible();
});
