import { devices, expect, test } from '@playwright/test';

for (const [device, glyph] of [['iPhone 13', 'smartphone'], ['iPad Pro 11', 'tablet'], ['Desktop Chrome', 'monitor']]) {
  test.describe(device, () => {
    test.use({ userAgent: devices[device].userAgent, hasTouch: devices[device].hasTouch, viewport: { width: 390, height: 844 } });
    test('system theme uses the device icon and follows later appearance changes', async ({ page }) => {
      await page.route('**/api/v1/**', route => route.fulfill({ json: {} }));
      await page.goto('/admin/import');
      const trigger = page.getByRole('button', { name: /^主题：/ });
      await expect(trigger.locator(`.lucide-${glyph}`)).toBeVisible();
      await trigger.focus();
      await page.keyboard.press('Enter');
      await expect(page.getByRole('menuitemradio', { name: '跟随系统' })).toBeChecked();
      await page.keyboard.press('Escape');
      await expect(trigger).toHaveAttribute('aria-expanded', 'false');
      await trigger.click();
      await page.getByRole('menuitemradio', { name: '浅色' }).click();
      await expect(trigger.locator('.lucide-sun')).toBeVisible();
      await trigger.click();
      await page.getByRole('menuitemradio', { name: '跟随系统' }).click();
      for (const colorScheme of ['dark', 'light'] as const) {
        await page.emulateMedia({ colorScheme });
        await expect(page.locator('html')).toHaveAttribute('data-theme', colorScheme);
        await expect(trigger.locator(`.lucide-${glyph}`)).toBeVisible();
      }
    });
  });
}
