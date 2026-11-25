import { expect, test, type Locator } from '@playwright/test';

async function expectReachable(control: Locator) {
  await control.scrollIntoViewIfNeeded();
  await expect.poll(() => control.evaluate(element => {
    const rect = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
  })).toBe(true);
}

test.beforeEach(async ({ page }) => {
  const groups = Array.from({ length: 40 }, (_, index) => ({ id: index + 1, name: `分组 ${index + 1}` }));
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session')) return route.fulfill({ json: { admin: true } });
    if (path.endsWith('/groups')) return route.fulfill({ json: groups });
    if (path.endsWith('/people')) return route.fulfill({ json: groups.map(group => ({ id: group.id, name: `人物 ${group.id}`, groups: [group], accounts: [] })) });
    if (path.endsWith('/monitors')) return route.fulfill({ json: [{ id: 1, platform: 'x', username: 'alice', interval_minutes: 60, paused: 1 }] });
    if (path.endsWith('/images')) return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } });
    return route.fulfill({ json: [] });
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });
});

for (const viewport of [{ width: 320, height: 568 }, { width: 568, height: 320 }, { width: 1280, height: 900 }]) {
  test(`resume controls stay reachable at ${viewport.width}×${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto('/admin/monitors');
    await page.getByRole('button', { name: '继续', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('恢复方式').click();
    const option = dialog.getByText('指定起始时间', { exact: true });
    await expectReachable(option);
    await option.click();
    const input = dialog.getByLabel('起始时间', { exact: true });
    await input.click();
    const panel = dialog.locator('.n-date-panel');
    await expect(panel.locator('..')).toHaveCSS('overflow', 'visible');
    await panel.locator('.n-time-picker input').click();
    await expectReachable(panel.locator('.n-time-picker-actions button').last());
    await expectReachable(panel.locator('.n-date-panel-actions button').last());
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth && element.clientHeight <= innerHeight)).toBe(true);
    await input.fill('2020-01-01 12:34:56');
    await input.press('Enter');
    await expectReachable(dialog.getByRole('button', { name: '确认恢复' }));
    await expect(dialog.getByRole('button', { name: '确认恢复' })).toBeEnabled();
  });
}

test('long option lists scroll inside short dialogs', async ({ page }) => {
  await page.setViewportSize({ width: 568, height: 320 });
  await page.goto('/admin/people');
  await page.getByRole('button', { name: '分组', exact: true }).click();
  await page.getByRole('button', { name: '编辑成员', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('.n-base-selection').click();
  const list = dialog.locator('.n-virtual-list');
  await expect(list).toBeVisible();
  expect(await list.evaluate(element => element.clientHeight < innerHeight / 2 && element.scrollHeight > element.clientHeight)).toBe(true);
  await list.evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expectReachable(dialog.getByText('人物 40', { exact: true }));
  await dialog.getByText('人物 40', { exact: true }).click();
  await expectReachable(dialog.getByRole('button', { name: '保存分组' }));

  await page.goto('/admin/review?state=all');
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  await dialog.locator('.people-cascader .n-base-selection').click();
  const column = dialog.locator('.n-cascader-submenu').first();
  expect(await column.evaluate(element => element.clientHeight <= innerHeight / 2)).toBe(true);
  await expectReachable(column.getByText('分组 40', { exact: true }));
  await expectReachable(dialog.getByRole('button', { name: '应用筛选' }));
});

test('a resized multiline input leaves the source dialog actions reachable', async ({ page }) => {
  await page.setViewportSize({ width: 568, height: 320 });
  await page.route('**/api/v1/admin/images?**', route => route.fulfill({ json: [{
    id: 1, width: 800, height: 600, detection: 'done', faces: [],
    sources: [{ id: 1, platform: 'x', author: 'fixture', author_name: '', published_at: null, url: 'https://x.com/fixture/status/1', post_text: '' }],
  }] }));
  await page.goto('/admin/review?state=all');
  await page.getByRole('button', { name: '补全 / 编辑' }).click();
  const dialog = page.getByRole('dialog', { name: '编辑来源' });
  const text = dialog.getByLabel('正文');
  await text.fill(Array.from({ length: 80 }, (_, index) => `第 ${index + 1} 行`).join('\n'));
  await dialog.locator('.n-input--textarea .n-input-wrapper').evaluate(element => { element.style.height = '700px'; });
  expect(await text.evaluate(element => {
    element.scrollTop = element.scrollHeight;
    return element.clientHeight <= innerHeight / 2 && element.scrollTop > 0 && element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
  })).toBe(true);
  await expectReachable(dialog.getByRole('button', { name: '保存来源' }));
  await dialog.getByRole('button', { name: '取消' }).click();
  await expect(dialog).toHaveCount(0);
});

test('a long tag collection keeps its add button reachable in a short dialog', async ({ page }) => {
  await page.setViewportSize({ width: 568, height: 320 });
  const hashtags = Array.from({ length: 80 }, (_, index) => `标签${index + 1}`);
  await page.route('**/api/v1/admin/monitors', route => route.fulfill({ json: [{ id: 1, platform: 'x', username: 'alice', interval_minutes: 60, paused: 0, hashtags }] }));
  await page.goto('/admin/monitors');
  await page.locator('.monitor-list').getByRole('button', { name: '更多' }).click();
  await page.getByRole('menuitem', { name: '修改标签' }).click();
  const dialog = page.getByRole('dialog');
  const tags = dialog.locator('.n-dynamic-tags');
  await expect(tags.locator('.n-tag')).toHaveCount(hashtags.length);
  expect(await tags.evaluate(element => element.clientHeight < innerHeight / 2 && element.scrollHeight > element.clientHeight)).toBe(true);
  await expectReachable(tags.getByRole('button', { name: '添加标签' }));
  await expectReachable(dialog.getByRole('button', { name: '确认修改' }));
});
