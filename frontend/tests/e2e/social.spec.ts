import { expect, test } from '@playwright/test';

for (const width of [390, 1280]) {
  test(`filtered RSS and post navigation at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 844 });
    const source = { platform: 'x', author: 'alice', author_name: '发布者', key: 'x:42', id: 42,
      published_at: '2025-11-01T12:34:56Z', url: 'https://x.com/alice/status/42' };
    const picture = { id: 1, image_id: 1, image_url: '/photo.svg', thumbnail_url: '/photo.svg', download_url: '/photo.svg',
      width: 600, height: 400, people: [], matched_source: source, sources: [source], source_count: 1 };
    await page.route('**/photo.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="#ccc"/><text x="250" y="200">布局示例</text></svg>' }));
    let avatarRequests = 0;
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/gallery')) return route.fulfill({ json: { items: [picture], total: 1, next_cursor: null } });
      if (path.endsWith('/gallery/1')) return route.fulfill({ json: picture });
      if (path.includes('/posts/')) return route.fulfill({ json: { ...source, coauthors: [], post_text: '第一行\n第二行\n#虹ヶ咲 #Day_1\nhttps://example.org/post#photo', images: [1,2,3].map(id => ({ ...picture, id })) } });
      if (path.includes('/publisher-avatars/')) return route.fulfill({ json: ++avatarRequests === 1 ? { image_url: null, pending: true } : { image_url: '/photo.svg', pending: false } });
      return route.fulfill({ json: path.endsWith('/site') ? { site_title: '图库' } : [] });
    });
    const raw = await request.get('/?people=3&photo=1&sort=oldest');
    expect(await raw.text()).toContain('href="/api/v1/gallery/rss.xml?people=3"');
    await page.goto('/?people=3&photo=1&sort=oldest');
    const photoDialog = page.getByRole('dialog', { name: '照片详情' });
    const postDialog = page.getByRole('dialog', { name: '帖子详情' });
    await expect(photoDialog.locator('.source-meta time')).toHaveText(/2025.*\d{2}:\d{2}:56/);
    await expect(photoDialog.locator('.source-meta a')).toHaveCount(0);
    await expect(page.locator('link[rel=alternate]')).toHaveCount(1);
    await page.getByRole('link', { name: 'X · 发布者' }).click();
    await expect(page).toHaveURL(/\/posts\/x:42\?people=3&sort=oldest$/);
    await expect(postDialog).toBeVisible();
    await postDialog.getByRole('button', { name: '关闭帖子详情' }).click();
    await expect(photoDialog).toBeVisible();
    await photoDialog.getByRole('link', { name: 'X · 发布者' }).click();
    await expect(page.locator('link[rel=alternate]')).toHaveCount(0);
    await expect(page.locator('.post-avatar img')).toBeVisible();
    await expect(page.locator('.post-header time')).toHaveText('2025年11月1日');
    const author = await postDialog.locator('.post-author').boundingBox();
    for (const selector of ['.post-copy', '.post-pictures']) {
      expect((await postDialog.locator(selector).boundingBox())?.x).toBe(author?.x);
    }
    await expect(postDialog.getByRole('link', { name: '#虹ヶ咲' })).toHaveAttribute('href', 'https://x.com/hashtag/' + encodeURIComponent('虹ヶ咲'));
    await expect(postDialog.getByRole('link', { name: 'https://example.org/post#photo' })).toHaveAttribute('href', 'https://example.org/post#photo');
    await page.locator('.post-header time').click();
    await expect(page.getByRole('tooltip')).toContainText(/:\d\d:56/);
    await page.locator('.post-copy').click();
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await expect(page.locator('.post-pictures a')).toHaveCount(3);
    for (const tile of await postDialog.locator('.post-pictures a').all()) {
      const bounds = await tile.boundingBox();
      expect(bounds).not.toBeNull();
      expect(Math.abs(bounds!.width - bounds!.height)).toBeLessThan(1);
    }
    await expect(page.locator('.post-pictures a').last()).toHaveAttribute('href', '/?people=3&sort=oldest&photo=3');
    await page.screenshot({ path: `/tmp/gallery-faces/social-${width}.png` });
    await postDialog.getByRole('link', { name: '查看照片 1' }).click();
    await expect(photoDialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(postDialog).toBeVisible();
    await page.getByRole('link', { name: '发布者 @alice' }).click();
    await expect(page).toHaveURL(/\/?\?publishers=x(?::|%3A)alice$/);
    const time = page.locator('.photo-card time');
    await time.click();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    const card = page.locator('.photo-card');
    await page.mouse.move(0, 0);
    await card.press('Tab');
    await page.keyboard.press('Shift+Tab');
    await expect(card).toBeFocused();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await card.press('Enter');
    await expect(photoDialog).toBeVisible();
    await time.dispatchEvent('pointerenter');
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await photoDialog.getByRole('button', { name: '关闭详情' }).click();
    await expect(photoDialog).toHaveCount(0);
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    if (width === 390) {
      await time.hover();
      await expect(page.getByRole('tooltip')).toBeVisible();
      await page.getByRole('button', { name: '筛选', exact: true }).click();
      await expect(page.getByRole('tooltip')).toHaveCount(0);
    }
    await expect(page.getByRole('link', { name: '订阅图库 RSS' })).toHaveAttribute('href', '/api/v1/gallery/rss.xml?publishers=x%3Aalice');
    await page.goto('/posts/x:42?people=3');
    await expect(postDialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(/\/\?people=3$/);
    await expect(postDialog).toHaveCount(0);
  });
}
