import { expect, test, type Page } from '@playwright/test';

async function expectAlignedFilters(page: Page) {
  const bounds = await page.locator('.publisher-toolbar .n-input, .publisher-toolbar .n-radio-button').evaluateAll(elements =>
    elements.map(element => { const { height, top } = element.getBoundingClientRect(); return { height, top }; }));
  expect(bounds.map(({ height }) => height)).toEqual([44, 44, 44]);
  expect(new Set(bounds.map(({ top }) => Math.round(top))).size).toBe(1);
}

test('page selection supports combined review, rule replacement and confirmed batch purge', async ({ page }) => {
  const accounts = ['alice', 'bob'].map(username => ({ username, label: username, linked: false, blocked: [] as string[], posts: 1 }));
  const usernames = accounts.map(item => item.username);
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/admin/publishers')) {
      const hasPosts = url.searchParams.get('view') === 'posts';
      const matches = accounts.filter(item => item.username.includes(url.searchParams.get('search') || ''));
      const items = matches.filter(item => hasPosts === !!item.posts);
      return route.fulfill({ json: { items, posts_count: matches.filter(item => item.posts).length, rules_count: matches.filter(item => !item.posts).length, page: 1, page_size: 30 } });
    }
    if (url.pathname.endsWith('/batch-rule')) {
      expect(route.request().postDataJSON()).toEqual({ usernames, blocked: ['quoted'] });
      accounts.forEach(item => { item.blocked = ['quoted']; });
    }
    if (url.pathname.endsWith('/batch-purge-preview')) {
      expect(route.request().postDataJSON()).toEqual({ usernames });
      return route.fulfill({ json: { posts: 2, exclusive: 1, shared: 2, references: [], blocked: ['quoted'], scope_token: 'batch-scope' } });
    }
    if (url.pathname.endsWith('/batch-purge')) {
      expect(route.request().postDataJSON()).toEqual({ usernames, blocked: null, scope_token: 'batch-scope' });
      accounts.forEach(item => { item.posts = 0; });
    }
    return route.fulfill({ json: url.pathname.endsWith('/site') ? { site_title: 'Gallery Faces' } : [] });
  });
  await page.goto('/admin/publishers');
  const all = page.getByRole('checkbox', { name: '全选本页' });
  const batch = page.getByRole('group', { name: '批量操作' });
  const dialog = page.getByRole('dialog');
  await page.getByRole('checkbox', { name: '选择 alice' }).check();
  await expect(all).toHaveAttribute('aria-checked', 'mixed');
  await page.getByPlaceholder('搜索昵称或用户名').fill('bob');
  await expect(all).not.toBeChecked();
  await expect(batch).toHaveCount(0);
  await page.getByPlaceholder('搜索昵称或用户名').fill('');
  await expect(page.getByRole('checkbox', { name: '选择 alice' })).toBeVisible();
  await all.check();
  await expect(batch.getByRole('link', { name: '查看审核' })).toHaveAttribute('href', /publishers=x%3Aalice,x%3Abob|publishers=x:alice,x:bob/i);
  await batch.getByRole('button', { name: '设置屏蔽' }).click();
  await expect(dialog).toContainText('2 位发布者');
  await dialog.getByRole('checkbox', { name: '引用' }).check();
  await dialog.getByRole('button', { name: '保存规则' }).click();
  await expect(page.getByText('1 个帖子 · 屏蔽：引用')).toHaveCount(2);
  await expect(batch).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await all.check();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/gallery-faces/publishers-batch-mobile.png' });
  await batch.getByRole('button', { name: '更多批量操作' }).click();
  await page.getByRole('menuitem', { name: '彻底删除帖子' }).click();
  await expect(dialog).toContainText('保留 2 张共享图片');
  await expect(dialog.getByRole('checkbox', { name: '保留各账号现有规则' })).toBeChecked();
  await dialog.getByRole('button', { name: '确认彻底删除' }).click();
  await page.getByRole('button', { name: '查看仅有屏蔽规则的账号' }).click();
  await all.check();
  await expect(batch.getByRole('button')).toHaveText(['编辑规则']);
  await expect(batch.getByRole('link')).toHaveCount(0);
});

test('publisher views, reference protection and purge with a discovery rule', async ({ page }) => {
  const account = { username: 'alice', label: '发布者甲', posts: 2, blocked: [] as string[], linked: false };
  let ownedReference = true;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/admin/publishers')) {
      const matches = url.searchParams.get('platform') === 'x' && account.username.includes(url.searchParams.get('search') || '') && (account.posts || account.blocked.length);
      const hasPosts = url.searchParams.get('view') === 'posts';
      return route.fulfill({ json: { items: matches && hasPosts === !!account.posts ? [account] : [], posts_count: matches && account.posts ? 1 : 0, rules_count: matches && !account.posts ? 1 : 0, page: 1, page_size: 30 } });
    }
    if (url.pathname.endsWith('/purge-preview')) return route.fulfill({ json: { posts: 2, exclusive: 1, shared: 1, blocked: [], scope_token: 'token', references: ownedReference ? [{ image_id: 8, reference_id: 12, person: '人物甲' }] : [] } });
    if (url.pathname.endsWith('/purge')) {
      expect(route.request().postDataJSON()).toEqual({ scope_token: 'token', blocked: ['quoted'] });
      account.posts = 0; account.blocked = ['quoted'];
    }
    if (url.pathname.endsWith('/rule')) account.blocked = route.request().postDataJSON().blocked;
    return route.fulfill({ json: url.pathname.endsWith('/site') ? { site_title: 'Gallery Faces' } : [] });
  });
  await page.goto('/admin/publishers');
  await expect(page.getByRole('heading', { name: '未关联发布者' })).toBeVisible();
  const nav = await page.locator('.admin-nav a').allTextContents();
  expect(nav.indexOf('未关联发布者')).toBe(nav.indexOf('重复图片') + 1);
  const profile = page.locator('.publisher-list').getByRole('link', { name: '发布者甲 @alice', exact: true });
  await expect(profile).toHaveAttribute('href', 'https://x.com/alice');
  await expect(profile).toHaveAttribute('target', '_blank');
  await expect(page.getByRole('link', { name: '查看审核' })).toHaveAttribute('href', /\/admin\/review\?state=all&publishers=x(?::|%3A)alice/);
  await page.getByText('Instagram', { exact: true }).click();
  await expect(page.getByText('此平台暂无有帖子的未关联发布者')).toBeVisible();
  await page.getByText('X', { exact: true }).click();
  await page.getByRole('radio', { name: /有帖子/ }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('radio', { name: /仅有屏蔽规则/ })).toBeChecked();
  await page.keyboard.press('ArrowLeft');
  await page.getByPlaceholder('搜索昵称或用户名').fill('alice');
  await expect(page.getByRole('link', { name: '查看审核' })).toBeVisible();
  await expectAlignedFilters(page);
  await expect(page.getByRole('button', { name: '设置屏蔽', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '更多操作 @alice' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/gallery-faces/publishers-desktop.png' });
  await page.getByRole('button', { name: '彻底删除帖子', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('参考 #12');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.setViewportSize({ width: 820, height: 900 });
  await expect(page.getByRole('button', { name: '更多操作 @alice' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expectAlignedFilters(page);
  await expect(page.getByRole('button', { name: '彻底删除帖子', exact: true })).toHaveCount(0);
  await expect(page.getByRole('radio', { name: /有帖子 1/ })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/gallery-faces/publishers-mobile.png' });
  await page.getByRole('button', { name: '更多操作 @alice' }).click();
  await page.getByRole('menuitem', { name: '彻底删除帖子', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('图片 #8 · 人物甲 · 参考 #12');
  await expect(dialog.getByRole('button', { name: '确认彻底删除' })).toBeDisabled();
  ownedReference = false;
  await dialog.getByRole('button', { name: '重新预览' }).click();
  await dialog.getByRole('checkbox', { name: '引用' }).check();
  await dialog.getByRole('button', { name: '确认彻底删除' }).click();
  await page.getByRole('button', { name: '查看仅有屏蔽规则的账号', exact: true }).click();
  await expect(page.getByRole('link', { name: '查看审核' })).toHaveCount(0);
  await expect(page.locator('.publisher-list')).toContainText('屏蔽：引用');
  await expect(profile).toHaveAttribute('href', 'https://x.com/alice');
  await page.getByRole('button', { name: '编辑规则' }).click();
  await dialog.getByRole('checkbox', { name: '引用' }).uncheck();
  await dialog.getByRole('button', { name: '保存规则' }).click();
  await expect(page.getByText('没有匹配的发布者')).toBeVisible();
});

test('a linked Instagram account can change its rule but cannot purge posts', async ({ page }) => {
  let blocked = ['all'];
  const label = '长昵称摄影工作室 · PortraitPhotographyArchive';
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/admin/publishers')) {
      const items = url.searchParams.get('platform') === 'instagram' ? [{ username: 'author', label, posts: 4, linked: true, blocked }] : [];
      return route.fulfill({ json: { items, posts_count: items.length, rules_count: 0, page: 1, page_size: 30 } });
    }
    if (url.pathname.endsWith('/rule')) blocked = route.request().postDataJSON().blocked;
    return route.fulfill({ json: url.pathname.endsWith('/site') ? { site_title: 'Gallery Faces' } : [] });
  });
  await page.goto('/admin/publishers');
  await page.getByText('Instagram', { exact: true }).click();
  await expect(page.locator('.publisher-list')).toContainText('已关联');
  await expect(page.getByRole('link', { name: `${label} @author`, exact: true })).toHaveAttribute('href', 'https://instagram.com/author');
  await expect(page.getByRole('button', { name: '彻底删除帖子' })).toHaveCount(0);
  await page.setViewportSize({ width: 320, height: 680 });
  await expect(page.getByRole('button', { name: '更多操作 @author' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const details = await page.locator('.publisher-list li > div').first().boundingBox();
  const actions = await page.locator('.publisher-list .publisher-actions').boundingBox();
  expect(actions!.y).toBeGreaterThanOrEqual(details!.y + details!.height);
  await page.screenshot({ path: '/tmp/gallery-faces/publishers-narrow-dark.png' });
  await page.getByRole('button', { name: '设置屏蔽', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('checkbox', { name: 'tagged' })).toBeDisabled();
  await expect(dialog.getByRole('link', { name: `${label} @author`, exact: true })).toHaveAttribute('href', 'https://instagram.com/author');
  await dialog.getByRole('checkbox', { name: '全部来源' }).uncheck();
  for (const name of ['tagged', '转发']) await dialog.getByRole('checkbox', { name }).check();
  await dialog.getByRole('button', { name: '保存规则' }).click();
  await expect(page.locator('.publisher-list')).toContainText('屏蔽：tagged、转发');
});
