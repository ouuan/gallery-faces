import { expect, test } from '@playwright/test';

test('avatar task details distinguish accounts with the same handle on different platforms', async ({ page }) => {
  const items = ['x', 'instagram'].map((platform, index) => ({
    id: index + 1, kind: 'avatar', status: 'done', done: 0, total: 0,
    payload: JSON.stringify({ platform, username: 'example' }), result: '{}',
  }));
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith('/tasks') ? { items, total: items.length, page: 1 }
      : path.endsWith('/session') || path.endsWith('/site') ? {} : [] });
  });
  await page.goto('/admin/import');
  for (const [index, platform] of ['X', 'Instagram'].entries()) {
    const row = page.getByRole('table', { name: '任务记录' }).locator('tbody').nth(index);
    await row.getByRole('button', { name: /展开任务/ }).click();
    await expect(row.getByText(`发布者账号：${platform} @example`, { exact: true })).toBeVisible();
  }
});
