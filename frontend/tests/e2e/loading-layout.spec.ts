import { test, expect, type Locator, type Route } from '@playwright/test';
import { test as matchTest } from '../room-fixture';

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
  for (const game of ['face-game', 'history-quiz']) matchTest(`${game} keeps its layout while loading at ${width}px`, async ({ guests }) => {
    const page = guests[0]!;
    const face = game === 'face-game';
    let release!: () => void;
    const delayed = new Promise<void>(resolve => { release = resolve; });
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/api/v1/**', async route => {
      if (route.request().resourceType() === 'image') await delayed;
      await route.fallback();
    });
    await page.goto(`/${game}?people=1-2`);
    await page.getByRole('button', { name: '开始游戏' }).click();
    await expect(page.getByText('正在加载照片…', { exact: true })).toBeVisible();
    const picture = page.locator(face ? '.game-picture' : '.picture');
    const controls = page.locator(face ? '.game-options' : '.date-step');
    const stage = await rect(picture), answers = await rect(controls);
    const answer = page.getByRole('button', { name: face ? '人1' : '提交日期', exact: true });
    await expect(answer).toBeDisabled();
    await expect(page.getByAltText('题目照片')).toBeHidden();
    release();
    await expect(answer).toBeEnabled();
    await stable(picture, stage);
    await stable(controls, answers);
  });

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
    const table = page.getByRole('table', { name: '任务记录' });
    await expect(table).toBeVisible();
    await page.clock.runFor(500);
    const before = await rect(table);
    hold = true;
    await page.clock.fastForward(3000);
    await expect.poll(() => !!held).toBe(true);
    await expect(page.getByText('正在加载任务记录…')).toBeHidden();
    await stable(table, before);
    await held!.fulfill({ json: { ...tasks, items: [{ ...tasks.items[0], done: 2, total: 2 }] } });
    await expect(table.getByText('2 / 2 张', { exact: true })).toBeVisible();
    await stable(table, before);
  });

  test(`person saving preserves geometry at ${width}px`, async ({ page }) => {
    let held: Route | undefined;
    await page.setViewportSize({ width, height: 1000 });
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === 'PUT') { held = route; return; }
      if (path.endsWith('/people')) return route.fulfill({ json: [{ id: 1, name: '人物甲', groups: [], accounts: [], reference_count: 0 }] });
      return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
    });
    await page.goto('/admin/people');
    await page.getByRole('button', { name: /^未分组 / }).click();
    await page.getByRole('button', { name: '编辑', exact: true }).click();
    await expect(page.getByText('暂无参考图', { exact: true })).toBeVisible();
    const save = page.getByRole('button', { name: '保存人物' });
    await save.scrollIntoViewIfNeeded();
    const buttonBefore = await rect(save);
    await save.click();
    await expect.poll(() => !!held).toBe(true);
    await expect(save).toHaveClass(/n-button--loading/);
    await stable(save, buttonBefore);
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
