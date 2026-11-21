import { test, expect, type Locator, type Route } from '@playwright/test';

async function rect(locator: Locator) {
  return locator.evaluate(el => {
    const { x, y, width, height } = el.getBoundingClientRect();
    return { x, y, width, height };
  });
}
async function stable(locator: Locator, before: Awaited<ReturnType<typeof rect>>) {
  const after = await rect(locator);
  for (const key of ['x', 'y', 'width', 'height'] as const)
    expect(Math.abs(after[key] - before[key]), key).toBeLessThanOrEqual(1);
}
for (const width of [390, 1280]) {
  test(`task polling preserves geometry at ${width}px`, async ({ page }) => {
    let held: Route | undefined;
    let hold = false;
    const tasks = { items: [{ id: 1, kind: 'import', status: 'done', payload: '{}', done: 1, total: 1 }], total: 1, page: 1 };
    await page.setViewportSize({ width, height: 900 });
    await page.clock.install();
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/tasks')) {
        if (hold) { held = route; return; }
        return route.fulfill({ json: tasks });
      }
      if (path.endsWith('/date-bounds')) return route.fulfill({ json: { current_offset_seconds: 0 } });
      return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
    });
    await page.goto('/admin/import');
    const table = page.locator('.task-table');
    await expect(table).toBeVisible();
    await page.clock.runFor(500);
    const before = await rect(table);
    hold = true;
    await page.clock.fastForward(3000);
    await expect.poll(() => !!held).toBe(true);
    await expect(page.getByText('正在加载任务记录…')).toBeVisible();
    await stable(table, before);
    await held!.fulfill({ json: tasks });
    await expect(page.getByText('正在加载任务记录…')).toHaveCount(0);
    await stable(table, before);
  });

  test(`person refresh and saving preserve geometry at ${width}px`, async ({ page }) => {
    let held: Route | undefined;
    let hold = false;
    const faces = [{ id: 11, image_id: 1, has_embedding: 1, is_reference: 0 }];
    await page.setViewportSize({ width, height: 1000 });
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/confirmed-faces')) {
        if (hold) { held = route; return; }
        return route.fulfill({ json: faces });
      }
      if (route.request().method() === 'PUT') { held = route; return; }
      if (path.endsWith('/people')) return route.fulfill({ json: [{ id: 1, name: '人物甲', groups: [], accounts: [], reference_count: 0 }] });
      if (path.endsWith('/crop')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>' });
      return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
    });
    await page.goto('/admin/people');
    await page.getByRole('button', { name: /^未分组 / }).click();
    await page.getByRole('button', { name: '编辑', exact: true }).click();
    const grid = page.locator('.confirmed-face-grid');
    await expect(grid).toBeVisible();
    // Let the dialog's opening transition settle before measuring.
    await page.waitForTimeout(350);
    const before = await rect(grid);
    hold = true;
    await page.getByRole('button', { name: '刷新人脸' }).click();
    await expect.poll(() => !!held).toBe(true);
    await stable(grid, before);
    await held!.fulfill({ json: faces });
    await expect(page.getByText('正在加载已确认人脸…')).toHaveCount(0);
    await stable(grid, before);
    const save = page.getByRole('button', { name: '保存人物' });
    await save.scrollIntoViewIfNeeded();
    const buttonBefore = await rect(save);
    held = undefined;
    await save.click();
    await expect.poll(() => !!held).toBe(true);
    await expect(save).toHaveClass(/n-button--loading/);
    await stable(save, buttonBefore);
    await page.screenshot({ path: `/tmp/gallery-faces/loading-${width}.png` });
    await held!.fulfill({ status: 500, json: { detail: '保存失败' } });
  });
}

test('review image and empty feedback loading do not shift the workspace', async ({ page }) => {
  const pending = new Map<string, Route>();
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/feedback')) { pending.set('feedback', route); return; }
    if (path.endsWith('/admin/media/1') && !route.request().url().includes('thumbnail')) {
      pending.set('image', route); return;
    }
    if (path.endsWith('/images')) return route.fulfill({ json: [{ id: 1, width: 800, height: 600, faces: [], sources: [], detection: 'done' }] });
    if (path.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
  });
  await page.goto('/admin/review');
  await expect.poll(() => pending.size).toBe(2);
  const preview = page.locator('.review-stage');
  const faces = page.locator('.review-faces');
  const previewBefore = await rect(preview), facesBefore = await rect(faces);
  await pending.get('feedback')!.fulfill({ json: { items: [], next_cursor: null } });
  await expect(page.getByText('正在加载反馈…')).toHaveCount(0);
  await stable(faces, facesBefore);
  await pending.get('image')!.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
  await expect(page.locator('.face-box-editor img')).toBeVisible();
  await stable(preview, previewBefore);
  await stable(faces, facesBefore);
});
