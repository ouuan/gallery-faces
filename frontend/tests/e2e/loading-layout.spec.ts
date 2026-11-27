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
  for (const game of ['face-game', 'history-quiz']) test(`${game} keeps its layout while drawing and loading at ${width}px`, async ({ page }) => {
    const face = game === 'face-game';
    const pending = new Map<string, Route>();
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith(`/gallery/${game}`)) { pending.set('question', route); return; }
      return route.fulfill({ json: /\/(site|session|date-bounds)$/.test(path) ? {} : [] });
    });
    await page.route('**/question.svg', route => { pending.set('photo', route); });
    await page.goto(`/${game}`);
    await page.getByRole('button', { name: '开始游戏' }).click();
    await expect(page.getByText('正在出题…', { exact: true })).toBeVisible();
    const picture = page.locator(face ? '.game-picture' : '.picture');
    const controls = page.locator(face ? '.game-options' : '.controls');
    const stage = await rect(picture), answers = await rect(controls);
    const choices = ['甲', '乙', '丙', '丁'].map((name, id) => ({ id: id + 1, name }));
    await expect.poll(() => pending.has('question')).toBe(true);
    await pending.get('question')!.fulfill({ json: { group_id: 1, image_id: 1, width: 800, height: 200, image_url: '/question.svg',
      ...(face ? { choices, face: { id: 1, person_id: 1, box: [10, 10, 50, 50] } }
        : { first_date: '2026-01-01', last_date: '2026-01-10', correct_date: '2026-01-08' }) } });
    const answer = page.getByRole('button', { name: face ? '甲' : '提交日期', exact: true });
    await expect(page.getByText('正在加载照片…', { exact: true })).toBeVisible();
    await expect(answer).toBeDisabled();
    await stable(picture, stage);
    await stable(controls, answers);
    await expect.poll(() => pending.has('photo')).toBe(true);
    await pending.get('photo')!.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200"/>' });
    await expect(answer).toBeEnabled();
    await stable(picture, stage);
    await stable(controls, answers);
    await answer.click();
    await page.getByRole('button', { name: '下一题' }).click();
    await expect(page.getByText('正在出题…', { exact: true })).toBeVisible();
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
