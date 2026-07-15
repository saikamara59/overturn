import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 390, height: 844 } });

test('mobile demo: chips + cards replace rail + table; card opens detail', async ({ page }) => {
  await page.goto('/');

  // worklist: card list + chip row, no table or rail
  await expect(page.locator('.claim-card').first()).toBeVisible();
  await expect(page.locator('.table-card')).toHaveCount(0);
  await expect(page.locator('.rail')).toHaveCount(0);
  await expect(page.locator('.chips')).toBeVisible();

  // a chip toggles active state (same filter state as the rail)
  const chip = page.locator('.chip').first();
  await chip.click();
  await expect(page.locator('.chip.on')).toHaveCount(1);
  await page.locator('.chip-reset').click();
  await expect(page.locator('.chip.on')).toHaveCount(0);

  // card → detail → back
  const firstId = await page.locator('.claim-card .cc-id').first().innerText();
  await page.locator('.claim-card').first().click();
  await expect(page.getByRole('button', { name: '← Worklist' })).toBeVisible();
  await expect(page.locator('.d-id')).toHaveText(firstId);
  await page.getByRole('button', { name: '← Worklist' }).click();

  // summary renders with the 2×2 stat grid present
  await page.getByRole('button', { name: 'Batch Summary' }).click();
  await expect(page.getByText('Records processed')).toBeVisible();
});
