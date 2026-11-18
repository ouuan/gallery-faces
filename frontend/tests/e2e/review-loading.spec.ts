import { test, expect } from '@playwright/test';

test('review lazily loads thumbnails and cancels the previous full image', async ({ page }) => {
  const thumbnails = new Set<number>();
  let originalStarted = false, originalCancelled = false;
  let feedbackStarted = false, feedbackCancelled = false;
  page.on('requestfailed', request => {
    if (request.url().endsWith('/admin/media/1')) originalCancelled = true;
    if (new URL(request.url()).pathname.endsWith('/admin/images/1/feedback')) feedbackCancelled = true;
  });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.endsWith('/admin/images/1/feedback')) { feedbackStarted = true; return; }
    if (path.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    const match = path.match(/\/admin\/media\/(\d+)$/);
    if (match) {
      const id = Number(match[1]);
      if (url.searchParams.has('thumbnail')) thumbnails.add(id);
      else if (id === 1) { originalStarted = true; return; }
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    }
    if (path.endsWith('/images')) return route.fulfill({ json: Array.from({ length: 200 }, (_, index) => ({
      id: index + 1, width: 800, height: 600, faces: [], sources: [], detection: 'done',
    })) });
    return route.fulfill({ json: /\/(session|site)$/.test(path) ? {} : [] });
  });
  await page.goto('/admin/review');
  await expect.poll(() => originalStarted).toBe(true);
  await expect.poll(() => feedbackStarted).toBe(true);
  await expect.poll(() => thumbnails.size).toBeGreaterThan(0);
  expect(thumbnails.size).toBeLessThan(200);
  expect(thumbnails.has(200)).toBe(false);
  await page.getByRole('button', { name: '下一组', exact: true }).click();
  await expect.poll(() => originalCancelled).toBe(true);
  await expect.poll(() => feedbackCancelled).toBe(true);
  await expect(page.locator('.face-box-editor img')).toBeVisible();
  await page.locator('.review-strip').evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await expect.poll(() => thumbnails.has(200)).toBe(true);
});
