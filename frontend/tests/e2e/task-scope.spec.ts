import { expect, test } from '@playwright/test';

test('expanded tasks show only their recorded feed options', async ({ page }) => {
  const cases = [
    { kind: 'download', url: 'https://x.com/example', scope: { retweets: false, quoted: false }, text: '不含转推、引用' },
    { kind: 'download', url: 'https://instagram.com/example', scope: { stories: true, tagged: true, reposts: false }, text: '包含快拍、tagged，不含转发' },
    { kind: 'monitor', url: 'https://instagram.com/example', scope: { stories: false, tagged: true }, text: '包含tagged，不含快拍' },
    { kind: 'download', url: 'https://x.com/example/status/123', scope: {}, text: '' },
    { kind: 'monitor', url: 'https://x.com/example', text: '' },
  ];
  const items = cases.map(({ kind, url, scope }, index) => ({
    id: index + 1, kind, status: 'done', done: 0, total: 0,
    payload: JSON.stringify({ url, scope }), result: '{}',
  }));
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith('/tasks') ? { items, total: items.length, page: 1 }
      : path.endsWith('/session') || path.endsWith('/site') ? {} : [] });
  });
  await page.goto('/admin/import');
  for (const [index, { text }] of cases.entries()) {
    const row = page.locator('.task-table tbody').nth(index);
    await row.getByRole('button', { name: /展开任务/ }).click();
    const scope = row.getByText(/^抓取范围：/);
    if (text) await expect(scope).toHaveText(`抓取范围：${text}`);
    else await expect(scope).toHaveCount(0);
    if (index === 1) {
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await row.screenshot({ path: `/tmp/gallery-faces/task-scope-${width}.png` });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
    }
  }
});
