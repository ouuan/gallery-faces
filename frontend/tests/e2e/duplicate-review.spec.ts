import { test, expect } from '@playwright/test';

test('round trips through member recognition links without losing the scoped pair', async ({ page }) => {
  const pairs = [[8, 20], [12, 30]];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/admin/images')) return route.fulfill({ json: [{ id: 12, group_id: 2, member_ids: [8, 12], member_count: 2,
      pending_duplicate_count: 1, width: 800, height: 600, faces: [], sources: [] }] });
    if (url.pathname.endsWith('/duplicates')) {
      if (!url.searchParams.has('image_id')) {
        expect(url.searchParams.getAll('decision')).toEqual(['pending']);
        return route.fulfill({ json: [] });
      }
      expect(url.searchParams.get('image_id')).toBe('12');
      expect(url.searchParams.getAll('decision')).toEqual([]);
      return route.fulfill({ json: { scope_group_id: 2, total: 2, page: 1, items: pairs.map(([a, b], index) => ({ a, b,
        decision: index ? 'separate' : 'pending', score: .9, images: [a, b].map(id => ({ id, group_id: id === a ? 2 : id,
          width: 800, height: 600, people: [], sources: [] })) })) } });
    }
    if (url.pathname.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? { admin: true } : [] });
  });
  await page.goto('/admin/review?state=unknown&image=12');
  await page.getByRole('link', { name: /审核重复图片.*1 组待审/ }).click();
  await expect(page.getByText('同组版本', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '#8', exact: true })).toHaveAttribute('href', '/admin/review?state=image&image=8');
  for (const [width, height] of [[1280, 900], [390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height });
    await expect(page.getByRole('button', { name: '合并为一组' })).toBeInViewport();
    await page.screenshot({ path: `/tmp/gallery-faces/scoped-duplicates-${width}.png` });
  }
  await page.getByRole('button', { name: '下一组' }).click();
  await expect(page.getByText('当前图片', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '#30' })).toHaveAttribute('href', '/admin/review?state=image&image=30');
  await page.getByRole('link', { name: '#12', exact: true }).click();
  await expect(page).toHaveURL(/state=image&image=12/);
  await page.goBack();
  await expect(page.locator('.duplicate-navigation')).toContainText('第 2 / 2 组');
  await page.getByRole('button', { name: '清除范围' }).click();
  await expect(page.getByText('当前状态下暂无重复图片候选')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/review\?state=unknown&image=12/);
});

test('compares post IDs and previews both images in place', async ({ page }) => {
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"/>' });
    if (!path.endsWith('/duplicates')) return route.fulfill({ json: /\/(session|site)$/.test(path) ? {} : [] });
    return route.fulfill({ json: [[12, 11], [13], []].map((posts, index) => {
      const a = index * 2 + 1;
      return { a, b: a + 1, decision: 'pending', score: .9, images: [[10, 11], posts].map((ids, side) => ({
        id: a + side, width: 80, height: 60, group_id: a + side, people: [],
        sources: ids.map(id => ({ id, platform: 'x', author: 'same-author' })),
      })) };
    }) });
  });
  await page.goto('/admin/duplicates');
  await expect(page.getByText('同一帖子', { exact: true })).toBeVisible();
  const compare = page.getByRole('button', { name: /按住对比/ });
  const left = page.getByAltText('重复图片候选 #1', { exact: true }), right = page.getByAltText('重复图片候选 #2');
  await compare.hover();
  await page.mouse.down();
  await expect(left).toBeVisible(); await expect(right).toBeHidden();
  const bounds = await left.boundingBox();
  await page.mouse.move(0, 0);
  await page.mouse.up();
  await expect(left).toBeHidden(); await expect(right).toBeVisible();
  expect(await right.boundingBox()).toEqual(bounds);
  await expect(left).toBeVisible({ timeout: 5000 }); await expect(right).toBeVisible();
  await compare.focus(); await page.keyboard.down('Space');
  await expect(right).toBeHidden(); await page.keyboard.up('Space');
  await expect(left).toBeHidden();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('不同帖子', { exact: true })).toBeVisible();
  await expect(page.locator('.duplicate-image:visible')).toHaveCount(2);
  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('帖子未知', { exact: true })).toBeVisible();
});

test('duplicate navigation fetches only the destination page', async ({ page }) => {
  const requested: number[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (!url.pathname.endsWith('/duplicates')) return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
    const number = Number(url.searchParams.get('page'));
    expect(url.searchParams.get('page_size')).toBe('50');
    requested.push(number);
    const items = Array.from({ length: number === 1 ? 50 : 1 }, (_, index) => ({
      a: 2 * (index + (number - 1) * 50) + 1, b: 2 * (index + (number - 1) * 50) + 2, decision: 'pending', score: .9, images: [],
    }));
    return route.fulfill({ json: { items, total: 51, page: number, page_size: 50 } });
  });
  await page.goto('/admin/duplicates');
  const nav = page.locator('.duplicate-navigation');
  await expect(nav).toContainText('第 1 / 51 组');
  for (let step = 0; step < 49; step++) await page.keyboard.press('ArrowRight');
  await expect(nav).toContainText('第 50 / 51 组');
  expect(requested).toEqual([1]);
  await page.keyboard.press('ArrowRight');
  await expect(nav).toContainText('第 51 / 51 组');
  await page.getByRole('button', { name: '上一组' }).click();
  await expect(nav).toContainText('第 50 / 51 组');
  expect(requested).toEqual([1, 2, 1]);
});

test('switching duplicate groups cancels unfinished image downloads', async ({ page }) => {
  const started = new Set<number>(), cancelled = new Set<number>();
  page.on('requestfailed', request => {
    const match = new URL(request.url()).pathname.match(/\/admin\/media\/(\d+)$/);
    if (match) cancelled.add(Number(match[1]));
  });
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const match = path.match(/\/admin\/media\/(\d+)$/);
    if (match) {
      const id = Number(match[1]);
      started.add(id);
      if (id <= 2) return; // Keep the first group's downloads pending.
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    }
    if (path.endsWith('/duplicates')) return route.fulfill({ json: [1, 3].map(a => ({
      a, b: a + 1, decision: 'pending', score: .9,
      images: [a, a + 1].map(id => ({ id, width: 800, height: 600, group_id: id, people: [], sources: [] })),
    })) });
    return route.fulfill({ json: /\/(session|site)$/.test(path) ? {} : [] });
  });
  await page.goto('/admin/duplicates');
  await expect.poll(() => [...started].sort()).toEqual([1, 2]);
  await page.getByRole('button', { name: '下一组' }).click();
  await expect.poll(() => [...cancelled].sort()).toEqual([1, 2]);
  await expect(page.locator('.duplicate-image img')).toHaveCount(2);
  await expect(page.getByText('图片加载失败', { exact: true })).toHaveCount(0);
  await expect(page.locator('.duplicate-heading')).toContainText('#3 与 #4');
});

test('duplicate review fits the viewport and advances to the next pair', async ({ page }) => {
  const image = (id: number, width: number, height: number) => ({
    id, width, height, group_id: id,
    people: [{ name: '很长的人物名称'.repeat(30) }],
    sources: Array.from({ length: 30 }, (_, i) => ({ id: i, platform: 'x', author: 'source', author_name: '发布者姓名', published_at: '2026-01-01', url: `https://x.com/source/status/${i}` })),
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
      return route.fulfill({ json: empty ? [] : rows.filter(row => { const states = new URL(route.request().url()).searchParams.getAll('decision'); return !states.length || states.includes(row.decision); }) });
    }
    if (path.endsWith('/tasks')) return route.fulfill({ json: { items: [], total: 0, page: 1 } });
    if (/\/(session|settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto('/admin/duplicates');
  await expect(page.locator('.duplicate-image img')).toHaveCount(2);
  await expect(page.locator('.duplicate-publishers').first().getByText('X · 发布者姓名', { exact: true })).toHaveCount(1);
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
    const compareBounds = (await page.getByRole('button', { name: /按住对比/ }).boundingBox())!;
    const actionBounds = (await page.getByRole('button', { name: '合并为一组' }).boundingBox())!;
    expect(compareBounds.y + compareBounds.height).toBeLessThanOrEqual(actionBounds.y);
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
  await expect(page.locator('.duplicate-navigation')).toContainText('第 1 / 1 组');
  await expect(page.locator('.duplicate-heading')).toContainText('#3 与 #4');
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: '/tmp/gallery-faces/duplicates-dark.png' });
  empty = true; await page.reload();
  await expect(page.getByText('当前状态下暂无重复图片候选')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
});

for (const scenario of [
  { name: 'middle', start: 1, all: false, remaining: [1, 5], expected: 5 },
  { name: 'last', start: 2, all: false, remaining: [1, 3], expected: 3 },
  { name: 'reordered history', start: 0, all: true, remaining: [5, 1, 3], expected: 3 },
  { name: 'missing successors', start: 0, all: false, remaining: [], expected: null },
]) test(`duplicate progression handles ${scenario.name} and refresh retry`, async ({ page }) => {
  const makeRow = (a: number) => ({ a, b: a + 1, decision: 'pending', score: .9,
    images: [a, a + 1].map(id => ({ id, width: 800, height: 600, group_id: id, people: [], sources: [] })) });
  let rows = [1, 3, 5].map(makeRow), posts = 0, failRefresh = false;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.includes('/media/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (path.endsWith('/duplicates')) {
      if (route.request().method() === 'POST') {
        posts++;
        expect(route.request().postDataJSON()).toEqual({ a: 1 + scenario.start * 2, b: 2 + scenario.start * 2, action: 'separate' });
        rows = scenario.remaining.map(makeRow);
        failRefresh = true;
        return route.fulfill({ json: { ok: true } });
      }
      if (failRefresh) return route.fulfill({ status: 503, json: { detail: '刷新失败测试' } });
      return route.fulfill({ json: rows });
    }
    if (/\/(session|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto('/admin/duplicates');
  const heading = page.locator('.duplicate-heading');
  await expect(heading).toContainText('#1 与 #2');
  if (scenario.all) {
    const response = page.waitForResponse(r => r.url().includes('/duplicates?') && !r.url().includes('decision='));
    await page.locator('.duplicate-filter').getByRole('button', { name: 'close' }).click();
    await response;
  }
  for (let i = 0; i < scenario.start; i++) await page.getByRole('button', { name: '下一组' }).click();
  await page.getByRole('button', { name: '不是重复', exact: true }).click();
  await expect(page.getByText(/已保存，列表刷新失败/)).toBeVisible();
  await expect(page.getByRole('button', { name: '不是重复', exact: true })).toBeDisabled();
  failRefresh = false;
  await page.getByRole('button', { name: '重试加载' }).click();
  if (scenario.expected) await expect(heading).toContainText(`#${scenario.expected} 与 #${scenario.expected + 1}`);
  else await expect(page.getByText('当前状态下暂无重复图片候选')).toBeVisible();
  expect(posts).toBe(1);
});

for (const [action, label, targets] of [
  ['delete_a', '仅左图 #1', '左图 #1'], ['delete_b', '仅右图 #2', '右图 #2'], ['delete_both', '两张都删', '左图 #1 和右图 #2'],
]) test(`duplicate review confirms the exact images for ${action}`, async ({ page }) => {
  if (action !== 'delete_a') await page.setViewportSize({ width: 390, height: 844 });
  const posts: unknown[] = [];
  let refreshFailed = false;
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/duplicates')) {
      if (route.request().method() === 'POST') {
        posts.push(route.request().postDataJSON());
        refreshFailed = true;
        return route.fulfill({ json: { ok: true } });
      }
      if (refreshFailed) return route.fulfill({ status: 503, json: { detail: '暂时不可用' } });
      return route.fulfill({ json: (posts.length ? [3] : [1, 3]).map(a => ({ a, b: a + 1, decision: 'pending', score: .9, images: [] })) });
    }
    return route.fulfill({ json: /\/(session|site)$/.test(path) ? {} : [] });
  });
  await page.goto('/admin/duplicates');
  const menu = page.getByRole('button', { name: '移入回收站' });
  const dialog = page.getByRole('dialog');
  await menu.click();
  await page.getByText(label, { exact: true }).click();
  await expect(dialog).toContainText(`将${targets}移入回收站`);
  await dialog.getByRole('button', { name: '取消' }).click();
  await expect(dialog).toHaveCount(0);
  expect(posts).toEqual([]);
  await expect(page.locator('.duplicate-heading')).toContainText('#1 与 #2');
  await menu.click();
  await page.getByText(label, { exact: true }).click();
  await dialog.getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.getByText(/已保存，列表刷新失败/)).toBeVisible();
  await expect(menu).toBeDisabled();
  refreshFailed = false;
  await page.getByRole('button', { name: '重试加载' }).click();
  await expect(page.locator('.duplicate-heading')).toContainText('#3 与 #4');
  expect(posts).toEqual([{ a: 1, b: 2, action }]);
});

test('duplicate status changes ignore stale responses', async ({ page }) => {
  let release: (() => void) | undefined;
  let initialDone: (() => void) | undefined;
  const done = new Promise<void>(resolve => { initialDone = resolve; });
  const row = (a: number) => ({ a, b: a + 1, decision: 'pending', score: .9, images: [] });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/duplicates')) {
      if (url.searchParams.has('decision')) {
        await new Promise<void>(resolve => { release = resolve; });
        await route.fulfill({ json: [row(1)] }); initialDone!(); return;
      }
      return route.fulfill({ json: [row(3)] });
    }
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
  });
  await page.goto('/admin/duplicates');
  await expect.poll(() => !!release).toBe(true);
  await page.locator('.duplicate-filter').getByRole('button', { name: 'close' }).click();
  await expect(page.locator('.duplicate-heading')).toContainText('#3 与 #4');
  release!(); await done;
  await expect(page.getByText('正在加载候选…')).toHaveCount(0);
  await expect(page.locator('.duplicate-heading')).toContainText('#3 与 #4');
});
