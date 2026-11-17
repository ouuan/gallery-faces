import { test, expect } from '@playwright/test';

test('anonymous feedback, pagination, throttling and moderation', async ({ page }) => {
  let admin = false, throttle = false, failList = true;
  const feedback: any[] = [];
  const source = { id: 1, platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/1' };
  const photo = { id: 7, image_id: 501, width: 800, height: 600, people: [], source_count: 1, matched_source: source, sources: [source] };
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    if (path.endsWith('/session')) return route.fulfill({ status: admin ? 200 : 401, json: { admin } });
    if (path.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith('/gallery')) return route.fulfill({ json: { items: [photo], next_cursor: null } });
    if (path.endsWith('/gallery/7')) return route.fulfill({ json: { ...photo, pending_feedback_count: feedback.filter(f => f.status === 'pending').length } });
    if (path.endsWith('/admin/images')) return route.fulfill({ json: [{ id: 501, width: 800, height: 600, detection: 'done', faces: [], sources: [source], pending_feedback_count: feedback.filter(f => f.status === 'pending').length }] });
    if (/\/admin\/feedback\/\d+$/.test(path)) {
      const index = feedback.findIndex(f => f.id === Number(path.split('/').pop()));
      if (method === 'DELETE') feedback.splice(index, 1);
      else Object.assign(feedback[index], route.request().postDataJSON());
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith('/feedback')) {
      if (method === 'POST') {
        expect(path).toBe('/api/v1/images/501/feedback');
        expect(route.request().headers()['x-gallery-request']).toBe('1');
        if (throttle) return route.fulfill({ status: 429, headers: { 'Retry-After': '2' }, json: { detail: '反馈提交过于频繁' } });
        const item = { id: feedback.length + 1, image_id: 501, content: route.request().postDataJSON().content, status: 'pending', created_at: '2026-01-01T00:00:00Z', resolved_at: null };
        feedback.unshift(item);
        return route.fulfill({ status: 201, json: item });
      }
      expect(path).toBe('/api/v1/admin/images/501/feedback');
      expect(admin).toBeTruthy();
      if (failList) { failList = false; return route.fulfill({ status: 500, json: { detail: '反馈加载失败' } }); }
      return route.fulfill({ json: { items: url.searchParams.has('before_id') ? feedback.slice(1) : feedback.slice(0, 1), next_cursor: feedback.length > 1 && !url.searchParams.has('before_id') ? feedback[0].id : null } });
    }
    return route.fulfill({ json: path.endsWith('/site') || path.endsWith('/settings') ? {} : [] });
  });
  await page.goto('/?photo=7');
  const panel = page.getByRole('region', { name: '图片反馈' });
  const input = panel.getByRole('textbox', { name: '反馈内容' });
  const submit = panel.getByRole('button', { name: '提交反馈', exact: true });
  const heading = panel.getByRole('heading', { level: 3 });
  await expect(heading).toHaveText('图片反馈');
  await expect(panel).toBeVisible();
  await expect(panel.getByText('反馈仅管理员可见。')).toBeVisible();
  await expect(input).toHaveAttribute('maxlength', '1000');
  await input.fill('字'.repeat(1001));
  await expect(input).toHaveValue('字'.repeat(1000));
  await input.fill('<script>alert(1)</script>\n人物识别需要修改');
  await submit.click();
  await expect(heading).toHaveText('图片反馈（已有 1 条反馈）');
  await expect(panel.locator('.feedback-content')).toHaveCount(0);
  await expect(panel.locator('script')).toHaveCount(0);
  await expect(input).toHaveValue('');
  throttle = true;
  await input.fill('保留草稿');
  await submit.click();
  await expect(submit).toBeDisabled();
  await expect(input).toHaveValue('保留草稿');
  await expect(submit).toBeEnabled({ timeout: 5000 });
  throttle = false;
  await submit.click();
  await expect(heading).toHaveText('图片反馈（已有 2 条反馈）');
  await expect(panel.locator('.feedback-content')).toHaveCount(0);
  await page.reload();
  await expect(heading).toHaveText('图片反馈（已有 2 条反馈）');
  await expect(panel).toBeVisible();
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: theme as 'light' | 'dark', reducedMotion: 'reduce' });
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: `/tmp/gallery-faces/feedback-${width}-${theme}.png` });
      expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBeTruthy();
    }
  }
  admin = true;
  await page.goto('/admin/review?image=501');
  await expect(page.getByText(/用户反馈（2 条待处理）/)).toBeVisible();
  await expect(panel.getByText('反馈加载失败', { exact: false })).toBeVisible();
  await panel.getByRole('button', { name: '重试', exact: true }).click();
  await panel.getByRole('button', { name: '加载更多反馈' }).click();
  await expect(panel.locator('.feedback-content')).toHaveCount(2);
  await expect(panel.locator('.feedback-content').last()).toHaveText('<script>alert(1)</script>\n人物识别需要修改');
  await expect(panel.locator('script')).toHaveCount(0);
  await panel.getByRole('button', { name: '标记已处理' }).first().click();
  await expect(panel.getByRole('button', { name: '恢复待处理' })).toBeVisible();
  await page.goto('/?photo=7');
  await expect(heading).toHaveText('图片反馈（已有 1 条反馈）');
  await page.goto('/admin/review?image=501');
  await panel.getByRole('button', { name: '恢复待处理' }).click();
  await expect(panel.getByRole('button', { name: '标记已处理' })).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  await panel.getByRole('button', { name: '删除反馈' }).click();
  await expect(page.getByText(/用户反馈（1 条待处理）/)).toBeVisible();
  await panel.getByRole('button', { name: '标记已处理' }).click();
  await page.goto('/?photo=7');
  await expect(heading).toHaveText('图片反馈');
});

test('a delayed submission cannot replace another image or its draft', async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let posted = false;
  const source = { id: 1, post_id: 1, platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/1' };
  const photos = [1, 2].map(id => ({ id, image_id: id + 10, width: 800, height: 600, people: [], source_count: 1, matched_source: source, sources: [source] }));
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/feedback')) {
      if (route.request().method() === 'POST') {
        posted = true;
        await gate;
        return route.fulfill({ status: 201, json: { id: 1 } });
      }
      return route.fulfill({ json: { items: [], next_cursor: null } });
    }
    if (path.endsWith('/gallery')) return route.fulfill({ json: { items: photos, next_cursor: null } });
    if (/\/gallery\/[12]$/.test(path)) return route.fulfill({ json: photos[Number(path.split('/').pop()) - 1] });
    if (path.endsWith('/session')) return route.fulfill({ status: 401, json: {} });
    if (path.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    return route.fulfill({ json: path.endsWith('/site') ? {} : [] });
  });
  await page.goto('/?photo=1');
  const input = page.getByRole('textbox', { name: '反馈内容' });
  await input.fill('第一张的反馈');
  await page.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expect.poll(() => posted).toBeTruthy();
  await page.getByRole('button', { name: '下一张', exact: true }).click();
  await expect(input).toHaveValue('');
  await input.fill('第二张的草稿');
  release();
  await expect(input).toHaveValue('第二张的草稿');
  await page.getByRole('button', { name: '上一张', exact: true }).click();
  await expect(input).toHaveValue('');
  await page.getByRole('button', { name: '下一张', exact: true }).click();
  await expect(input).toHaveValue('第二张的草稿');
});
