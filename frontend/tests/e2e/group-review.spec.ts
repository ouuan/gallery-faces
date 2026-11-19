import { test, expect, type Page, type Route } from '@playwright/test';

const source = { id: 10, platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/1', image_ids: [1, 2] };
function group(id = 2) {
  return { id, group_id: 10, member_ids: id === 2 ? [1, 2] : [1, 2, 4], member_count: id === 2 ? 2 : 3,
    incomplete_image_ids: [1], width: 800, height: 600, detection: 'done', pending_feedback_count: 2,
    sources: [source], faces: [{ id: id * 10, image_id: id, box: [100, 100, 100, 100], person_id: 7,
      locked: false, ignored: false, candidates: [{ person_id: 8, score: 0.9 }], revision: 0 }],
  };
}
const second = { ...group(3), group_id: 20, member_ids: [3], member_count: 1, sources: [], faces: [], incomplete_image_ids: [], pending_feedback_count: 0 };
async function defaults(page: Page, handler: (route: Route, url: URL) => Promise<boolean>) {
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (await handler(route, url)) return;
    if (url.pathname.includes('/media/') || url.pathname.endsWith('/crop'))
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (url.pathname.endsWith('/people')) return route.fulfill({ json: [7, 8].map(id => ({ id, name: `人物${id}`, groups: [], accounts: [] })) });
    return route.fulfill({ json: /\/(site|settings|session)$/.test(url.pathname) ? { admin: true } : [] });
  });
}

test('member links resolve to one group, with all sources and paginated feedback', async ({ page }) => {
  const feedbackScopes: string[] = [];
  await defaults(page, async (route, url) => {
    if (url.pathname.endsWith('/admin/images')) {
      await route.fulfill({ json: [group(), second] }); return true;
    }
    if (url.pathname.endsWith('/images/2/feedback')) {
      feedbackScopes.push(url.searchParams.get('scope') || '');
      const more = url.searchParams.has('before_id');
      await route.fulfill({ json: { items: [{ id: more ? 1 : 2, image_id: more ? 1 : 2, content: more ? '小版本的反馈' : '代表图的反馈',
        status: 'pending', created_at: '2026-01-01T00:00:00Z' }], next_cursor: more ? null : 2 } }); return true;
    }
    return false;
  });
  await page.goto('/admin/review?state=review&image=1');
  await expect(page).toHaveURL(/image=2/);
  await expect(page.locator('.review-strip button')).toHaveCount(2);
  await expect(page.locator('.review-main > .review-heading h3')).toHaveText('图片 #2 · 共 2 个版本');
  await expect(page.locator('.review-sources')).toContainText('来源待补全：#1');
  await expect(page.locator('.source-members')).toHaveText('图片 #1、#2');
  await page.getByRole('button', { name: '加载更多反馈' }).click();
  await expect(page.locator('.feedback-content')).toHaveText(['代表图的反馈', '小版本的反馈']);
  await expect(page.locator('.feedback-meta').last()).toContainText('图片 #1');
  expect(feedbackScopes).toEqual(['group', 'group']);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
      await page.locator('.review-heading').first().scrollIntoViewIfNeeded();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: `/tmp/gallery-faces/group-review-${width}-${colorScheme}.png`, fullPage: true });
    }
  }
  await page.getByRole('button', { name: '下一张', exact: true }).click();
  await expect(page).toHaveURL(/image=3/);
  await page.getByRole('button', { name: '上一张', exact: true }).click();
  await expect(page).toHaveURL(/image=2/);
});

test('a changed representative rejects an old edit, preserves the choice, then refreshes the same group', async ({ page }) => {
  let current = group(), reads = 0;
  await defaults(page, async (route, url) => {
    if (url.pathname.endsWith('/admin/images')) {
      reads++;
      await route.fulfill({ json: [current, second] }); return true;
    }
    if (url.pathname.endsWith('/admin/faces/20')) {
      expect(route.request().postDataJSON().person_id).toBe(8);
      await route.fulfill({ status: 409, json: { detail: '代表图已变化，请刷新后审核当前代表图' } }); return true;
    }
    return false;
  });
  await page.goto('/admin/review?state=image&image=1');
  await expect(page).toHaveURL(/image=2/);
  await page.locator('.face-review label').filter({ has: page.getByRole('radio', { name: /人物8/ }) }).click();
  current = group(4);
  await page.locator('.face-review').getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.getByText('代表图已变化，请刷新后审核当前代表图')).toBeVisible();
  await expect(page.getByRole('radio', { name: /人物8/ })).toBeChecked();
  expect(reads).toBe(1);
  await expect(page.locator('.review-main > .review-heading h3')).toContainText('图片 #2');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '确认', exact: true }).click();
  await expect(page.locator('.review-main > .review-heading h3')).toHaveText('图片 #4 · 共 3 个版本');
  await expect(page).toHaveURL(/image=4/);
  expect(reads).toBe(2);
});

test('a completed group leaves the queue and advances to the following group', async ({ page }) => {
  let complete = false;
  const first = { ...group(), incomplete_image_ids: [], pending_feedback_count: 0 };
  await defaults(page, async (route, url) => {
    if (url.pathname.endsWith('/admin/images')) {
      await route.fulfill({ json: complete ? [second] : [first, second] }); return true;
    }
    if (url.pathname.endsWith('/admin/faces')) {
      expect(route.request().postDataJSON().faces.map((face: any) => face.id)).toEqual([20]);
      complete = true;
      await route.fulfill({ json: { saved: [20], failures: [] } }); return true;
    }
    return false;
  });
  await page.goto('/admin/review');
  await page.getByRole('button', { name: '全部确认', exact: true }).click();
  await expect(page.locator('.review-strip button')).toHaveCount(1);
  await expect(page.locator('.review-main > .review-heading h3')).toHaveText('图片 #3 · 共 1 个版本');
  await expect(page).toHaveURL(/image=3/);
});

test('manual refresh reveals new feedback for an unchanged representative and allows moderation', async ({ page }) => {
  let feedback: { id: number; image_id: number; content: string; status: string; created_at: string }[] = [];
  let feedbackReads = 0;
  await defaults(page, async (route, url) => {
    if (url.pathname.endsWith('/admin/images')) {
      await route.fulfill({ json: [{ ...group(), pending_feedback_count: feedback.filter(item => item.status === 'pending').length }] });
      return true;
    }
    if (url.pathname.endsWith('/images/2/feedback')) {
      expect(url.searchParams.get('scope')).toBe('group');
      expect(url.searchParams.has('before_id')).toBe(false);
      feedbackReads++;
      await route.fulfill({ json: { items: feedback, next_cursor: null } });
      return true;
    }
    if (url.pathname.endsWith('/admin/feedback/1')) {
      expect(route.request().postDataJSON()).toEqual({ status: 'resolved' });
      feedback[0].status = 'resolved';
      await route.fulfill({ json: feedback[0] });
      return true;
    }
    return false;
  });
  await page.goto('/admin/review?state=image&image=2');
  await expect.poll(() => feedbackReads).toBe(1);
  await expect(page.getByText('正在加载反馈…')).toHaveCount(0);
  await expect(page.locator('.feedback-panel')).toHaveCount(0);
  feedback = [{ id: 1, image_id: 1, content: '刚收到的同组反馈', status: 'pending', created_at: '2026-01-01T00:00:00Z' }];
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.locator('.review-main > .review-heading h3')).toHaveText('图片 #2 · 共 2 个版本');
  await expect(page.locator('.feedback-content')).toHaveText('刚收到的同组反馈');
  await expect(page.locator('.feedback-panel')).toContainText('1 条待处理');
  expect(feedbackReads).toBe(2);
  // A manual refresh must reload content even if the pending count is unchanged.
  feedback[0].content = '反馈内容已更新';
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.locator('.feedback-content')).toHaveText('反馈内容已更新');
  expect(feedbackReads).toBe(3);
  await page.getByRole('button', { name: '标记已处理', exact: true }).click();
  await expect(page.getByRole('button', { name: '恢复待处理', exact: true })).toBeVisible();
  await expect(page.getByText('用户反馈（1 条待处理）')).toHaveCount(0);
  expect(feedbackReads).toBe(4);
});
