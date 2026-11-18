import { test, expect } from '@playwright/test';

test('duplicate review fits the viewport and preserves the selected pair', async ({ page }) => {
  const image = (id: number, width: number, height: number) => ({
    id, width, height, group_id: id,
    people: [{ name: '很长的人物名称'.repeat(30) }],
    sources: Array.from({ length: 30 }, (_, i) => ({ id: i, platform: 'x', author: 'source', published_at: '2026-01-01', url: `https://x.com/source/status/${i}` })),
  });
  let rows = [
    { a: 1, b: 2, decision: 'pending', score: 0.95, images: [image(1, 600, 3000), image(2, 3000, 600)] },
    { a: 3, b: 4, decision: 'pending', score: 0, images: [image(3, 40, 30), image(4, 800, 600)] },
  ];
  const original = [...rows];
  let fail = false, empty = false;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes('/media/')) {
      const photo = original.flatMap(r => r.images).find(i => path.endsWith('/' + i.id))!;
      return route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="${photo.width}" height="${photo.height}"><rect width="100%" height="100%" fill="#8799aa"/><rect x="1" y="1" width="${photo.width - 2}" height="${photo.height - 2}" fill="none" stroke="#20242b" stroke-width="2"/></svg>` });
    }
    if (path.endsWith('/duplicates')) {
      if (route.request().method() === 'POST') {
        expect(route.request().postDataJSON()).toEqual({ a: 1, b: 2, action: 'merge' });
        if (fail) return route.fulfill({ status: 503, json: { detail: '测试提交失败' } });
        rows = [original[1], { ...original[0], decision: 'merge' }];
        return route.fulfill({ json: { ok: true } });
      }
      return route.fulfill({ json: empty ? [] : rows });
    }
    if (path.endsWith('/tasks')) return route.fulfill({ json: { items: [], total: 0, page: 1 } });
    if (/\/(session|settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto('/admin/duplicates');
  await expect(page.locator('.duplicate-image img')).toHaveCount(2);
  for (const size of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }, { width: 390, height: 844 }, { width: 844, height: 390 }]) {
    await page.setViewportSize(size);
    await expect(page.locator('.duplicate-image img').first()).toBeVisible();
    const geometry = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
      elements: [...document.querySelectorAll('.duplicate-image, .duplicate-image img, .duplicate-actions button')].map(el => {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height, overflow: el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1 };
      }),
    }));
    expect(geometry.width).toBeLessThanOrEqual(size.width);
    expect(geometry.height).toBeLessThanOrEqual(size.height);
    for (const r of geometry.elements) {
      expect(r.x).toBeGreaterThanOrEqual(0); expect(r.y).toBeGreaterThanOrEqual(0);
      expect(r.right).toBeLessThanOrEqual(size.width); expect(r.bottom).toBeLessThanOrEqual(size.height);
      expect(r.width).toBeGreaterThan(0); expect(r.height).toBeGreaterThan(0); expect(r.overflow).toBe(false);
    }
    await expect(page.locator('.duplicate-image img').first()).toHaveCSS('object-fit', 'scale-down');
    await page.screenshot({ path: `/tmp/gallery-faces/duplicates-${size.width}.png` });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const details = page.getByRole('button', { name: '查看图片 #1 详情' });
  await details.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByRole('link')).toHaveCount(30);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(details).toBeFocused();
  const prev = page.getByRole('button', { name: '上一组' });
  const next = page.getByRole('button', { name: '下一组' });
  await expect(prev).toBeDisabled(); await next.click(); await expect(next).toBeDisabled();
  await expect(page.locator('.duplicate-heading')).toContainText('0.000');
  await prev.click();
  fail = true; await page.getByRole('button', { name: '合并为一组' }).click();
  await expect(page.getByText('测试提交失败')).toBeVisible();
  await expect(page.locator('.duplicate-heading')).toContainText('#1 与 #2');
  fail = false; await page.getByRole('button', { name: '合并为一组' }).click();
  await expect(page.locator('.duplicate-navigation')).toContainText('第 2 / 2 组');
  await expect(page.locator('.duplicate-heading')).toContainText('#1 与 #2');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: '/tmp/gallery-faces/duplicates-dark.png' });
  empty = true; await page.reload();
  await expect(page.getByText('暂无重复图片候选')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
});
