import { expect, test } from '@playwright/test';

for (const [mode, label] of [['daily', '每日一图'], ['random', '随机图片']]) {
  for (const width of [390, 1280]) test(`${mode} links preserve the selected filters at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const imagePath = '/api/v1/media/42';
    const requests: string[] = [];
    await page.route('**/api/v1/**', route => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith(`/${mode}`)) {
        requests.push(url.search);
        return route.fulfill({ json: { date: '2026-11-22', group_id: mode === 'random' ? requests.length : 7, image_url: imagePath } });
      }
      if (url.pathname === imagePath) return route.fulfill({ contentType: 'image/png',
        body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jAscAAAAASUVORK5CYII=', 'base64') });
      if (url.pathname.endsWith('/gallery')) return route.fulfill({ json: { items: [], total: 0, next_cursor: null } });
      return route.fulfill({ json: /\/(groups|people)$/.test(url.pathname) ? [] : {} });
    });
    await page.goto('/?sort=oldest');
    if (width < 600) await page.getByRole('button', { name: '筛选', exact: true }).click();
    await page.getByRole('checkbox', { name: '包含无人脸图片' }).check();
    const entry = page.getByRole('link', { name: label, exact: true });
    await expect(entry).toHaveText('');
    await entry.click();
    await expect(page).toHaveURL(new RegExp(`/${mode}\\?include_no_faces=true$`));
    await expect(page.getByRole('link', { name: '在图库中查看' })).toHaveAttribute('href', `/?include_no_faces=true&photo=${mode === 'random' ? 1 : 7}`);
    await page.reload();
    await expect(page.getByRole('img', { name: mode === 'daily' ? `2026-11-22 的${label}` : label, exact: true })).toBeVisible();
    const date = page.getByText('2026-11-22', { exact: true });
    if (mode === 'daily') await expect(date).toBeVisible();
    else await expect(date).toHaveCount(0);
    await expect(page.locator('.draw-picture')).toHaveAttribute('aria-busy', 'false');
    await expect(page.getByRole('link', { name: '图片直链' })).toHaveAttribute('href', `/api/v1/gallery/${mode}/image?include_no_faces=true`);
    await expect(page.getByRole('link', { name: '在图库中查看' })).toHaveAttribute('href', `/?include_no_faces=true&photo=${mode === 'random' ? 2 : 7}`);
    expect(requests).toEqual(['?include_no_faces=true', '?include_no_faces=true']);
  });
}

test('daily page retries temporary failures and preserves filters for empty results', async ({ page }) => {
  let temporary = true;
  await page.route('**/api/v1/gallery/daily?*', route => route.fulfill({ status: temporary ? 503 : 404,
    json: { detail: temporary ? '图片暂不可用，请稍后重试' : '当前筛选下没有可展示的照片' } }));
  await page.goto('/daily?people=3');
  await expect(page.getByText('图片暂不可用，请稍后重试')).toBeVisible();
  temporary = false;
  await page.getByRole('button', { name: '重试' }).click();
  await expect(page.getByText('当前筛选下没有可展示的照片')).toBeVisible();
  await expect(page.getByRole('link', { name: '返回图库' })).toHaveAttribute('href', '/?people=3');
});

test('daily title changes page text but not the draw or the image link', async ({ page }) => {
  let search: string | undefined;
  await page.route('**/api/v1/gallery/daily?*', route => {
    search = new URL(route.request().url()).search;
    return route.fulfill({ json: { date: '2026-11-22', group_id: 7, image_url: '/favicon.svg' } });
  });
  await page.route('**/favicon.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>' }));
  for (const [value, title] of [['  精选 & 合照  ', '精选 & 合照'], ['   ', '每日一图']]) {
    await page.goto('/daily?' + new URLSearchParams({ people: '3', title: value }));
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
    await expect(page).toHaveTitle(new RegExp(` · ${title}$`));
    await expect(page.getByRole('img', { name: `2026-11-22 的${title}` })).toBeVisible();
    await expect(page.getByRole('link', { name: '图片直链' })).toHaveAttribute('href', '/api/v1/gallery/daily/image?people=3');
    expect(search).toBe('?people=3');
  }
});
