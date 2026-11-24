import { expect, test } from '@playwright/test';

const source = { platform: 'x', author: 'alice', author_name: '发布者', key: 'x:42', id: 42,
  published_at: '2025-11-01T12:34:56Z', url: 'https://x.com/alice/status/42' };
const picture = { id: 1, image_id: 1, image_url: '/photo.svg', thumbnail_url: '/photo.svg', download_url: '/photo.svg',
  width: 600, height: 400, people: [], matched_source: source, sources: [source], source_count: 1 };

test.describe('unavailable post thumbnails', () => {
  test.use({ hasTouch: true });
  for (const width of [390, 1280]) {
    test(`disabled picture at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      const thumbnail = '/api/v1/posts/x:42/thumbnails/2';
      const requests: string[] = [];
      await page.route('**/api/v1/**', route => {
        const path = decodeURIComponent(new URL(route.request().url()).pathname);
        requests.push(path);
        if (path === thumbnail) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>' });
        if (path === '/api/v1/posts/x:42') return route.fulfill({ json: { ...source, coauthors: [], images: [picture, { ...picture, id: 2, image_url: null, thumbnail_url: thumbnail }, { ...picture, id: 3 }] } });
        if (path.endsWith('/gallery/1')) return route.fulfill({ json: picture });
        if (path.endsWith('/gallery')) return route.fulfill({ json: { items: [picture], total: 1, next_cursor: null } });
        return route.fulfill({ json: path.endsWith('/site') ? { site_title: '图库' } : [] });
      });
      await page.goto('/posts/x:42');
      const dialog = page.getByRole('dialog', { name: '帖子详情' });
      const tile = dialog.getByRole('group', { name: '照片 2' });
      const hint = page.getByRole('tooltip', { name: '图片无法查看' });
      const normal = dialog.getByRole('link', { name: '查看照片 1' });
      await expect(tile.getByRole('button')).toBeDisabled();
      await expect(tile.locator('img')).toHaveJSProperty('naturalWidth', 100);
      expect((await tile.boundingBox())!.width).toBeCloseTo((await normal.boundingBox())!.width, 0);
      await expect(hint).toBeHidden();
      if (width === 390) {
        await tile.tap();
        await expect(hint).toBeVisible();
        await dialog.getByRole('heading', { name: '帖子详情' }).tap();
      } else {
        await tile.hover();
        await expect(hint).toBeVisible();
        await normal.hover();
        await expect(hint).toBeHidden();
        await normal.press('Tab');
        await expect(tile).toBeFocused();
        await expect(hint).toBeVisible();
        await page.keyboard.press('Enter');
        await page.keyboard.press('Tab');
      }
      await expect(hint).toBeHidden();
      await expect(page).toHaveURL(/\/posts\/x:42$/);
      expect(requests).not.toContain('/api/v1/gallery/2');
      expect(requests.some(path => path.startsWith('/api/v1/media/'))).toBe(false);
      await normal.click();
      await expect(page.getByRole('dialog', { name: '照片详情' })).toBeVisible();
    });
  }
});

for (const width of [390, 1280]) {
  test(`post picture rows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/photo.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"/>' }));
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.includes('/posts/')) {
        const count = Number(decodeURIComponent(path).split(':').pop());
        return route.fulfill({ json: { ...source, coauthors: [], images: Array.from({ length: count }, (_, index) => ({ ...picture, id: index + 1 })) } });
      }
      if (path.endsWith('/gallery')) return route.fulfill({ json: { items: [], total: 0, next_cursor: null } });
      return route.fulfill({ json: path.endsWith('/site') ? { site_title: '图库' } : [] });
    });
    for (const expectedRows of [[1], [2, 2], [3], [2, 3], [2, 2, 3]]) {
      const count = expectedRows.reduce((sum, size) => sum + size, 0);
      await page.goto(`/posts/x:${count}`);
      const grid = page.locator('.post-pictures');
      await expect(grid.getByRole('link')).toHaveCount(count);
      const { rows, gridWidth, gap } = await grid.evaluate(element => {
        const rows = new Map<number, number[]>();
        for (const tile of element.querySelectorAll('a')) {
          const row = rows.get(tile.offsetTop) ?? [];
          row.push(tile.offsetWidth);
          rows.set(tile.offsetTop, row);
        }
        return { rows: [...rows.values()], gridWidth: element.clientWidth, gap: parseFloat(getComputedStyle(element).columnGap) };
      });
      expect(rows.map(row => row.length)).toEqual(expectedRows);
      for (const row of rows) {
        const expectedWidth = (gridWidth - gap * (row.length - 1)) / row.length;
        for (const tileWidth of row) expect(Math.abs(tileWidth - expectedWidth)).toBeLessThan(1);
      }
      if (count === 1) await expect(grid.locator('img')).toHaveCSS('object-fit', 'contain');
    }
  });

  test(`filtered RSS and post navigation at ${width}px`, async ({ page, request }) => {
    await page.setViewportSize({ width, height: 844 });
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
    const card = page.getByRole('button', { name: '查看 未知人物 的照片' });
    const time = card.getByRole('time');
    await time.click();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('heading', { name: '照片库' }).hover();
    const closePhoto = photoDialog.getByRole('button', { name: '关闭详情' });
    for (const dismiss of [() => closePhoto.click(), () => closePhoto.press('Enter')]) {
      await card.press('Tab');
      await page.keyboard.press('Shift+Tab');
      await expect(card).toBeFocused();
      await expect(page.getByRole('tooltip')).toBeVisible();
      await card.press('Enter');
      await expect(photoDialog).toBeVisible();
      await time.dispatchEvent('pointerenter');
      await expect(page.getByRole('tooltip')).toBeHidden();
      await dismiss();
      await expect(photoDialog).toBeHidden();
      await expect(card).toBeFocused();
      await expect(page.getByRole('tooltip')).toBeHidden();
    }
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
