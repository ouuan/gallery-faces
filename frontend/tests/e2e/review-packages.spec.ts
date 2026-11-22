import { expect, test as base, type Page } from '@playwright/test';
import { createServer, request } from 'node:http';
import { request as secureRequest } from 'node:https';
import type { AddressInfo } from 'node:net';
import type { components } from '../../src/schema';

const root = '/api/v1/admin/review-packages';
const test = base.extend<{ archiveServer: { origin: string; requests: string[] } }>({
  archiveServer: async ({ baseURL }, use) => {
    const requests: string[] = [];
    const server = createServer((incoming, response) => {
      const path = incoming.url!;
      if (path.startsWith(`${root}/exports/`) && path.endsWith('/download')) {
        requests.push(`${incoming.method} ${path}`);
        response.writeHead(200, { 'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename="review-test.zip"' });
        response.end(Buffer.from('504b0506000000000000000000000000000000000000', 'hex'));
      } else {
        const url = new URL(path, baseURL);
        const upstream = (url.protocol === 'https:' ? secureRequest : request)(url, { headers: { ...incoming.headers, host: url.host } }, result => {
          response.writeHead(result.statusCode!, result.headers);
          result.pipe(response);
        });
        upstream.on('error', () => { response.writeHead(502); response.end(); });
        incoming.pipe(upstream);
      }
    });
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    try { await use({ origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}`, requests }); }
    finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
  },
});
const queue = '/admin/review?view=suggestions';
const image = { id: 41, width: 800, height: 600, faces: [], sources: [], detection: 'done' };
type Fixture = components['schemas']['QueueItem'];
const item = { id: 101, batch: 'example', status: 'pending', image_id: 41, width: 800, height: 600,
  proposal: { id: 'match-41', image_id: 41, kind: 'match', reason: '与已确认的参考图对照，左侧人脸的面部特征一致。', face_id: 5, person_id: 7, confidence: 'high' },
  current: '未知人物 · 未确认', proposed: '林青 · 已确认', box: [100, 120, 160, 180], reference_ids: [3],
  member_ids: [41, 52], scope_token: null, attachment: null } satisfies Fixture;
const external = { ...item, id: 102, proposal: { id: 'ref', image_id: 41, kind: 'add_reference', person_id: 7,
  source: { attachment: 'attachments/test.jpg' }, reason: '将右侧人脸作为参考。' },
  current: '林青 · 1 张参考图', proposed: '添加至林青的参考图', box: null,
  attachment: { width: 800, height: 600, boxes: [[100, 120, 160, 180], [510, 130, 180, 190]], suggested_index: null } } satisfies Fixture;
const recycle = { ...item, id: 103, image_id: 53, proposal: { id: 'recycle', image_id: 53, kind: 'recycle', reason: '符合本批回收标准。' },
  current: '在库 3 张', proposed: '整组 3 张移入回收站', scope_token: 'exact-group', member_ids: [53, 54, 55], box: null, reference_ids: [] } satisfies Fixture;
const label = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#afb8c3"/><text x="400" y="440" text-anchor="middle" font-size="24">布局示例</text></svg>';
async function mockQueue(page: Page, items: Fixture[]) {
  await page.route(`**${root}/suggestions?**`, route => {
    const params = new URL(route.request().url()).searchParams;
    const status = params.get('status');
    const filtered = items.filter(entry => status === 'review' ? ['pending', 'recorded'].includes(entry.status) : entry.status === status);
    const number = Math.min(Number(params.get('page')), Math.max(1, Math.ceil(filtered.length / 20)));
    return route.fulfill({ json: { items: filtered.slice((number - 1) * 20, number * 20), total: filtered.length, page: number, page_size: 20 } });
  });
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith('/download')) return route.fallback();
    if (/\/media\/|\/crop$|\/attachment$/.test(path)) return route.fulfill({ contentType: 'image/svg+xml', body: label });
    if (path.endsWith('/session')) return route.fulfill({ json: { admin: true } });
    if (path.endsWith('/site') || path.endsWith('/settings')) return route.fulfill({ json: {} });
    if (path.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith('/admin/images')) return route.fulfill({ json: url.searchParams.has('image_id') ? [image] : { items: [image], total: 51, page: 1, page_size: 50 } });
    return route.fulfill({ json: [] });
  });
});

test('exports all filtered groups directly and downloads the finished ZIP', async ({ page, archiveServer }) => {
  const body = { ids: [], image_id: null, state: 'unknown', people: '2,7', publishers: 'x:someone', match: 'all', start: '2026-01-01', end: '2026-02-01' };
  const job = { id: 'batch', status: 'building', done: 0, total: 51, error: null };
  await page.clock.install();
  await page.route(`**${root}/exports`, route => {
    expect(route.request().postDataJSON()).toEqual(body);
    return route.fulfill({ json: job });
  });
  let status = 'ready';
  await page.route(`**${root}/exports/batch`, route => route.fulfill({ json: { ...job, status, done: 51 } }));
  await page.goto(`${archiveServer.origin}/admin/review?state=unknown&people=2,7&publishers=x:someone&match=all&start=2026-01-01&end=2026-02-01`);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出全部结果 51 张' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('review-test.zip');
  expect(await file.failure()).toBeNull();
  await expect(page.getByRole('link', { name: '手动下载' })).toHaveAttribute('href', `${root}/exports/batch/download`);
  await page.reload();
  await expect(page.getByRole('link', { name: '手动下载' })).toBeVisible();
  status = 'downloaded';
  await page.clock.fastForward(60000);
  await expect(page.getByRole('link', { name: '手动下载' })).toHaveCount(0);
  expect(archiveServer.requests).toEqual([`GET ${root}/exports/batch/download`]);
  await page.reload();
  await expect(page.getByRole('button', { name: '导出全部结果 51 张' })).toBeVisible();
  await expect(page.getByRole('link', { name: '手动下载' })).toHaveCount(0);
  expect(archiveServer.requests).toHaveLength(1);
});

test('resumes the selected export after navigation and permits another after expiry', async ({ page }) => {
  const posts: unknown[] = [];
  let polls = 0;
  await mockQueue(page, []);
  await page.route(`**${root}/exports`, route => {
    posts.push(route.request().postDataJSON());
    return route.fulfill({ json: { id: 'new-job', status: 'building', total: 1, done: 0 } });
  });
  let status = 'building';
  await page.route(`**${root}/exports/new-job`, route => { polls++; return route.fulfill({ json: { id: 'new-job', status, total: 1, done: 0 } }); });
  await page.clock.install();
  await page.goto('/admin/review?state=all');
  await page.getByRole('button', { name: '全选本页' }).click();
  await page.getByRole('button', { name: '导出所选 1 张' }).click();
  await page.getByRole('link', { name: '建议复核' }).click();
  await expect(page.getByRole('heading', { name: '暂无建议或审核结论' })).toBeVisible();
  const previous = polls;
  await page.clock.fastForward(5000);
  expect(polls).toBe(previous);
  await page.goto('/admin/review?state=image&image=41');
  await expect(page.getByRole('button', { name: '正在生成 0 / 1' })).toBeDisabled();
  expect(posts).toHaveLength(1);
  status = 'expired';
  await page.clock.fastForward(5000);
  await expect(page.getByRole('alert').filter({ hasText: '重新导出' })).toBeVisible();
  await page.getByRole('button', { name: '导出当前图片 #41' }).click();
  await expect.poll(() => posts).toEqual([{ state: 'all', ids: [41], image_id: null }, { state: 'all', ids: [], image_id: 41 }]);
});

test('imports without applying changes, reloads the queue, and requires a valid external face', async ({ page }) => {
  const rows: Fixture[] = [];
  const decisions: unknown[] = [];
  await mockQueue(page, rows);
  let finished = false;
  await page.route(`**${root}/imports`, route => {
    expect(route.request().headers()['content-type']).toContain('multipart/form-data');
    expect(route.request().postDataBuffer()?.toString()).toContain('name="file"; filename="result.zip"');
    return route.fulfill({ status: 202, json: { id: 'import', status: 'queued' } });
  });
  await page.route(`**${root}/imports/import`, route => {
    if (!finished) return route.fulfill({ json: { id: 'import', status: 'running' } });
    if (!rows.length) rows.push({ ...external }, { ...external, id: 108, attachment: { ...external.attachment, boxes: [] } },
      { ...external, id: 109, attachment: { ...external.attachment, boxes: [[50, 100, 70, 80]] } });
    return route.fulfill({ json: { id: 'import', status: 'done', added: 3, recorded: 0, duplicates: 1 } });
  });
  await page.route(`**${root}/decisions`, route => {
    const body = route.request().postDataJSON();
    decisions.push(body);
    rows.find(entry => entry.id === body.items[0].id)!.status = body.decision === 'accept' ? 'accepted' : 'rejected';
    return route.fulfill({ json: { applied: [body.items[0].id], failures: [] } });
  });
  await page.goto(queue);
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '导入审核结果' }).click();
  await (await chooser).setFiles({ name: 'result.zip', mimeType: 'application/zip', buffer: Buffer.from('result') });
  await expect(page.getByText(/正在后台导入/)).toBeVisible();
  await expect(page.getByRole('button', { name: '刷新建议' })).toBeEnabled();
  await page.reload();
  await expect(page.getByText(/正在后台导入/)).toBeVisible();
  finished = true;
  await expect(page.getByText('已导入 3 条建议，记录 0 条审核结论，跳过 1 条重复记录。')).toBeVisible();
  const multi = page.getByRole('article', { name: '建议 #102' });
  const empty = page.getByRole('article', { name: '建议 #108' });
  await expect(multi.getByRole('button', { name: '接受', exact: true })).toBeDisabled();
  await expect(empty.getByRole('button', { name: '接受', exact: true })).toBeDisabled();
  const single = page.getByRole('article', { name: '建议 #109' });
  await expect(single.getByRole('button', { name: '接受', exact: true })).toBeDisabled();
  await single.getByText('人脸 1', { exact: true }).click();
  await expect(single.getByRole('button', { name: '接受', exact: true })).toBeEnabled();
  await multi.getByText('人脸 2', { exact: true }).click();
  await multi.getByRole('button', { name: '接受', exact: true }).click();
  await empty.getByRole('button', { name: '拒绝', exact: true }).click();
  await expect.poll(() => decisions).toEqual([{ decision: 'accept', items: [{ id: 102, face_index: 1 }] }, { decision: 'reject', items: [{ id: 108 }] }]);
  await page.locator('[aria-label="建议状态"]').click();
  await page.locator('.n-base-select-option').filter({ hasText: '已拒绝' }).click();
  await page.reload();
  await expect(empty).toBeVisible();
  await expect(empty.getByRole('button', { name: '接受' })).toHaveCount(0);
});

test('confirms the exact selected group and keeps failed suggestions actionable', async ({ page }) => {
  const rows: Fixture[] = [{ ...item }, { ...external }, { ...recycle }];
  await mockQueue(page, rows);
  const posts: unknown[] = [];
  await page.route(`**${root}/decisions`, route => {
    posts.push(route.request().postDataJSON());
    rows[2].status = 'accepted';
    return route.fulfill({ json: { applied: [103], failures: [{ id: 101, detail: '人脸已修改，请重新核对' }] } });
  });
  await page.goto(queue);
  await page.getByRole('checkbox', { name: /建议 #101$/ }).check();
  await page.getByRole('checkbox', { name: /建议 #103$/ }).check();
  await page.getByRole('button', { name: '接受所选' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('图片 #53 的整组 3 张：#53、#54、#55');
  await dialog.getByRole('button', { name: '取消' }).click();
  expect(posts).toEqual([]);
  await page.getByRole('button', { name: '接受所选' }).click();
  await dialog.getByRole('button', { name: '确认接受' }).click();
  await expect(page.getByText('建议 #101：人脸已修改，请重新核对')).toBeVisible();
  expect(posts).toEqual([{ decision: 'accept', items: [{ id: 101 }, { id: 103, scope_token: 'exact-group' }] }]);
  await expect(page.getByRole('checkbox', { name: /建议 #101$/ })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: /建议 #102$/ })).not.toBeChecked();
});

test('offers a manual download when the automatic link is blocked', async ({ page, archiveServer }) => {
  await page.addInitScript(() => {
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      if (!this.href.endsWith('/download')) click.call(this);
    };
  });
  await page.route(`**${root}/exports`, route => route.fulfill({ json: { id: 'fallback', status: 'ready', total: 1, done: 1 } }));
  await page.goto(`${archiveServer.origin}/admin/review?state=image&image=41`);
  await page.getByRole('button', { name: '导出当前图片 #41' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: '手动下载' }).click();
  expect((await download).suggestedFilename()).toBe('review-test.zip');
  expect(archiveServer.requests).toEqual([`GET ${root}/exports/fallback/download`]);
});

test('clears selection on page changes and restores the queue page on reload', async ({ page }) => {
  await mockQueue(page, Array.from({ length: 21 }, (_, index) => ({ ...item, id: index + 1 })));
  await page.goto(queue);
  await page.getByRole('checkbox', { name: /建议 #1$/ }).check();
  await page.getByRole('navigation', { name: '建议分页' }).getByRole('button', { name: '下一页' }).click();
  await expect(page.getByRole('article', { name: '建议 #21' })).toBeVisible();
  await expect(page.getByRole('button', { name: '接受所选' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByRole('article', { name: '建议 #21' })).toBeVisible();
});

test('distinguishes optional confidence tiers without numeric scores', async ({ page }) => {
  const tiers = ['high', 'medium', 'low'] as const;
  const labels = ['高', '中', '低'];
  const icons = ['signal-high', 'signal-medium', 'signal-low'];
  await mockQueue(page, [...tiers.map((confidence, index) => ({ ...item, id: index + 1, proposal: { ...item.proposal, confidence } })), external]);
  await page.goto(queue);
  for (const [index, label] of labels.entries()) {
    const entry = page.getByRole('article', { name: `建议 #${index + 1}`, exact: true });
    await expect(entry.getByText(`Agent 置信度：${label}`, { exact: true })).toBeVisible();
    await expect(entry.locator(`.confidence svg.lucide-${icons[index]}`)).toBeVisible();
  }
  await expect(page.getByRole('article', { name: '建议 #102', exact: true }).locator('.confidence')).toHaveCount(0);
});

test('shows the exact source change and distinguishes a review note from a gallery edit', async ({ page }) => {
  const source: Fixture = { ...item, proposal: { id: 'source', image_id: 41, kind: 'correct_source', post_id: 5,
    field: 'author_name', value: '林青', reason: '与原帖署名一致。' }, current: '帖子 #5 · 发布者名称：未填写',
    proposed: '帖子 #5 · 发布者名称：林青（所有引用此帖的图片共用）', box: null, reference_ids: [] };
  const note: Fixture = { ...source, id: 102, status: 'recorded', proposal: { id: 'note', image_id: 41, kind: 'review_outcome',
    outcome: 'needs_human', reason: '第二张图片没有可用预览。' }, current: '仅记录本批审核结论，不修改图库', proposed: '证据不足，请人工复核' };
  const noteOnly = { ...note, id: 103, image_id: 42, proposal: { ...note.proposal, image_id: 42 } };
  await mockQueue(page, [source, note, noteOnly]);
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(queue);
    await expect(page.getByRole('heading', { name: /更正帖子来源/ })).toBeVisible();
    await expect(page.getByText(source.proposed, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '查看审核结论' })).toHaveCount(0);
    await expect(page.getByRole('article', { name: '建议 #101' }).getByRole('button', { name: '接受', exact: true })).toBeEnabled();
    for (const record of [note, noteOnly]) {
      const group = page.getByRole('region', { name: `图片 #${record.image_id} 的审核记录` });
      const entry = group.getByRole('article', { name: `结论 #${record.id}` });
      await expect(entry.getByText(record.proposed, { exact: true })).toBeVisible();
      await expect(entry.getByText(record.proposal.reason, { exact: true })).toBeVisible();
      await expect(entry.getByRole('button')).toHaveCount(0);
      await expect(entry.getByRole('checkbox')).toHaveCount(0);
    }
    await page.getByRole('link', { name: '图片 #41', exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/review\?state=image&image=41$/);
  }
});

test('groups evidence and reflows the review workspace without horizontal overflow', async ({ page }) => {
  await mockQueue(page, [item, external, recycle]);
  await page.goto(queue);
  const group = page.getByRole('region', { name: '图片 #41 的审核记录' });
  await expect(group.getByRole('article')).toHaveCount(2);
  await expect(group.getByText('Agent 置信度：高', { exact: true })).toBeVisible();
  await expect(group.getByRole('article').nth(1).getByText('Agent 置信度', { exact: false })).toHaveCount(0);
  await expect(group.getByAltText('图片 #41', { exact: true })).toBeVisible();
  await expect(group.getByText('定位（x, y, 宽, 高）：[100, 120, 160, 180] px')).toBeVisible();
  const nav = page.getByRole('navigation', { name: '审核工作区' });
  await expect(nav.locator('[aria-current="page"]')).toHaveText('建议复核');
  for (const width of [1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const preview = (await group.getByAltText('图片 #41', { exact: true }).boundingBox())!;
    const changes = (await group.getByRole('article').first().boundingBox())!;
    if (width >= 1280) expect(preview.x + preview.width).toBeLessThanOrEqual(changes.x);
    else expect(preview.y + preview.height).toBeLessThanOrEqual(changes.y);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    if (width === 390) {
      await page.getByLabel('主题', { exact: true }).click();
      await page.locator('.n-base-select-option').filter({ hasText: '深色' }).click();
      await page.reload();
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
      await expect(page.getByLabel('主题', { exact: true })).toContainText('深色');
      await expect.poll(() => page.locator('.queue-tools .n-base-selection-label').evaluate(element => {
        const channels = getComputedStyle(element).backgroundColor.match(/\d+(\.\d+)?/g)?.map(Number) ?? [];
        const base = getComputedStyle(document.body).backgroundColor.match(/\d+/g)!.map(Number);
        const alpha = channels[3] ?? 1;
        return Math.max(...channels.slice(0, 3).map((value, index) => value * alpha + base[index] * (1 - alpha))) < 100;
      })).toBe(true);
      await expect(page.getByRole('button', { name: '导入审核结果' })).toBeEnabled();
    }
    if (width === 1280 || width === 390) await page.screenshot({ path: `/tmp/gallery-faces/review-packages-${width}.png` });
  }
});
