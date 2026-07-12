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

  // dismiss the second claim with a reason; it leaves the default worklist
  await page.getByRole('button', { name: '← Worklist' }).click();
  await page.getByText('CLM-E2E-2').first().click();
  await page.getByRole('button', { name: 'Dismiss' }).click();
  await page.getByLabel(/reason/i).selectOption('too_small');
  await page.getByRole('button', { name: /confirm dismiss/i }).click();
  await expect(page.getByText(/won't appeal/i)).toBeVisible();

  await page.getByRole('button', { name: '← Worklist' }).click();
  await expect(page.getByText('CLM-E2E-2')).not.toBeVisible();

  // reload → still dismissed; reveal via the status filter and restore
  await page.reload();
  await expect(page.getByText('CLM-E2E-2')).not.toBeVisible();
  await page.locator('.fitem', { hasText: 'Dismissed' }).click();  // status filter row
  await page.getByText('CLM-E2E-2').first().click();
  await page.getByRole('button', { name: 'Restore' }).click();
  await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
});

test('multi-tenant onboarding: provision org → invite → isolated workspace', async ({ page, browser }) => {
  // platform admin provisions a new org
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();
  await page.getByRole('button', { name: 'Admin' }).click();

  const orgName = `E2E Org ${Date.now()}`;
  await page.getByLabel(/organization name/i).fill(orgName);
  await page.getByRole('button', { name: /create org/i }).click();
  const inviteUrl = await page
    .locator('input[readonly]').first().inputValue();
  expect(inviteUrl).toContain('#/invite/');

  // new user accepts in a fresh browser context (separate cookies)
  const ctx = await browser.newContext();
  const invitee = await ctx.newPage();
  await invitee.goto(inviteUrl);
  await invitee.getByLabel(/email/i).fill(`founder-${Date.now()}@e2e.test`);
  await invitee.getByLabel(/password/i).fill('freshpw123');
  await invitee.getByRole('button', { name: /join/i }).click();

  // lands in an empty, isolated org
  await expect(invitee.getByText('Runs', { exact: true })).toBeVisible();
  await expect(invitee.getByText(orgName)).toBeVisible();
  await expect(invitee.getByText(/No runs yet/)).toBeVisible();
  await ctx.close();
});

const MESSY_CSV = `Claim Number,Carrier,Adj Group,Reason Code,Remark Codes,Denial Reason,Total Charges,DOS,Check Date,Batch ${Date.now()}
CLM-MAP-${Date.now()}-1,Acme Ins,CO,50,N115,Not medically necessary,"$12,500.00",04/10/2026,05/01/2026,batch-a
CLM-MAP-${Date.now()}-2,Acme Ins,PR,204,,Plan exclusion,430.25,03/02/2026,04/15/2026,batch-a
`;

test('messy CSV maps, imports with deadline rule, and remembers the mapping', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByLabel(/email/i).fill(process.env.E2E_EMAIL ?? 'admin@example.com');
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? 'change-me-locally');
  await page.getByRole('button', { name: /log in/i }).click();

  // unique per run: the dev DB is never cleaned between test runs, so a
  // fixed filename would let `.first()` below match a stale completed row
  // from an earlier run before this run's own row ever appears.
  const filename = `waystar-export-${Date.now()}.csv`;
  const upload = async () => {
    await page.setInputFiles('input[type=file]', {
      name: filename, mimeType: 'text/csv',
      buffer: Buffer.from(MESSY_CSV),
    });
  };

  // first upload: mapping panel appears with suggestions pre-filled
  await upload();
  await expect(page.getByText('Map your columns')).toBeVisible();
  await expect(page.getByLabel('Claim ID')).toHaveValue('Claim Number');
  await expect(page.getByText(/denial date \+ \d+ days/)).toBeVisible();
  await page.getByRole('button', { name: /use this mapping/i }).click();
  await page.getByRole('button', { name: /upload/i }).click();

  const row = page.locator('.audit-row', { hasText: filename }).first();
  await expect(row.getByText('completed')).toBeVisible({ timeout: 90_000 });

  // second upload of the same shape: saved mapping badge, no panel
  await upload();
  await expect(page.getByText(/using saved mapping/i)).toBeVisible();
  await expect(page.getByText('Map your columns')).not.toBeVisible();
});
