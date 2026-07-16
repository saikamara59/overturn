import { expect, test } from '@playwright/test';

const STAMP = Date.now();
const CSV = `claim_id,payer,carc_code,rarc_codes,denial_reason_text,billed_amount,service_date,denial_date,appeal_deadline
CLM-GEN-${STAMP}-1,Synthetic Payer A,CO-50,N115,Not deemed a medical necessity.,1200.00,2026-04-10,2026-05-01,2026-09-30
CLM-GEN-${STAMP}-2,Synthetic Payer B,CO-197,M62,Authorization absent.,845.50,2026-04-12,2026-05-02,2026-10-15
`;

test('worklist Generate Appeals and detail Regenerate re-draft claims', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  await page.setInputFiles('input[type=file]', {
    name: `gen-${STAMP}.csv`, mimeType: 'text/csv', buffer: Buffer.from(CSV),
  });
  await page.getByRole('button', { name: /upload/i }).click();
  const row = page.locator('.audit-row', { hasText: `gen-${STAMP}.csv` }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });
  await row.click();

  // bulk: select all → Generate Appeals → drafts come back
  await expect(page.getByText(`CLM-GEN-${STAMP}-1`)).toBeVisible();
  await page.locator('.thead .cbox').click();
  await page.getByRole('button', { name: 'Generate Appeals' }).click();
  await expect(page.getByText(/Appeal generation queued for 2 claims/)).toBeVisible();
  await expect(page.locator('.table-card .st', { hasText: 'Draft Ready' })).toHaveCount(2, { timeout: 90_000 });

  // the requeue really happened server-side: audit trail records it
  await page.getByRole('button', { name: 'Batch Summary' }).click();
  await expect(page.getByText('regeneration_requested').first()).toBeVisible();
  await page.getByRole('button', { name: 'Worklist', exact: true }).click();

  // detail: Regenerate a single claim
  await page.getByText(`CLM-GEN-${STAMP}-1`).click();
  await page.getByRole('button', { name: 'Regenerate' }).click();
  await expect(page.getByText(/queued for regeneration/)).toBeVisible();
  await expect(page.locator('.d-head .st', { hasText: 'Draft Ready' }))
    .toBeVisible({ timeout: 90_000 });
  await expect(page.locator('.letter')).not.toBeEmpty();
});
