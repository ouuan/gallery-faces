import { test, expect } from '@playwright/test';

test('refreshing review metadata preserves the loaded original', async ({ page }) => {
  let originals = 0;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/admin/media/')) {
      if (!url.searchParams.has('thumbnail')) originals++;
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    }
    if (url.pathname.endsWith('/admin/images')) return route.fulfill({ json: [{
      id: 1, width: 800, height: 600, faces: [], sources: [], detection: 'done',
    }] });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
  });
  await page.goto('/admin/review');
  const photo = page.locator('.face-box-editor img');
  await expect(photo).toBeVisible();
  const originalUrl = await photo.getAttribute('src');
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await expect(page.getByText('正在加载审核项目…')).toHaveCount(0);
    await expect(photo).toBeVisible();
  }
  console.log(`Original downloads after initial load + 3 metadata refreshes: ${originals}`);
  expect(originals).toBe(1);
  await expect(photo).toHaveAttribute('src', originalUrl!);
});
