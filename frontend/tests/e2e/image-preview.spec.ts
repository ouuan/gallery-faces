import { test, expect, type Route } from '@playwright/test';

for (const width of [390, 1280]) {
  for (const surface of ['gallery', 'review', 'duplicates']) {
    test(`${surface} shows a thumbnail while downloading at ${width}px`, async ({ page }) => {
      const pending: Route[] = [];
      const source = { id: 1, platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/1' };
      const photo = { id: 1, image_id: 1, width: 800, height: 600, people: [], faces: [], sources: [source], matched_source: source, source_count: 1, image_url: '/api/v1/media/full', thumbnail_url: '/api/v1/media/thumb' };
      const svg = (width: number, height: number) => `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#8799aa"/></svg>`;
      await page.setViewportSize({ width, height: 900 });
      await page.route('**/api/v1/**', route => {
        const url = new URL(route.request().url()), path = url.pathname;
        if (path.includes('/media/')) {
          if (path.endsWith('/thumb') || url.searchParams.has('thumbnail')) return route.fulfill({ contentType: 'image/svg+xml', body: svg(160, 120) });
          pending.push(route); return;
        }
        if (path.endsWith('/gallery')) return route.fulfill({ json: { items: [photo], next_cursor: null } });
        if (path.endsWith('/gallery/1')) return route.fulfill({ json: photo });
        if (path.endsWith('/images')) return route.fulfill({ json: [photo] });
        if (path.endsWith('/duplicates')) return route.fulfill({ json: [{ a: 1, b: 2, decision: 'pending', score: .9, images: [photo, { ...photo, id: 2 }] }] });
        if (path.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
        return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
      });
      await page.goto(surface === 'gallery' ? '/?photo=1' : `/admin/${surface}`);
      const container = page.locator(surface === 'gallery' ? '.detail-image' : surface === 'review' ? '.face-box-editor' : '.duplicate-image').first();
      const image = container.locator('img');
      await expect.poll(() => pending.length).toBe(surface === 'duplicates' ? 2 : 1);
      await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBe(160);
      await expect(container).toHaveAttribute('aria-busy', 'true');
      await page.screenshot({ path: `/tmp/gallery-faces/preview-${surface}-${width}.png` });
      await pending[0]!.fulfill({ contentType: 'image/svg+xml', body: svg(800, 600) });
      await expect(image).toHaveAttribute('src', /^blob:/);
      await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBe(800);
      await expect(container).toHaveAttribute('aria-busy', 'false');
      if (surface === 'duplicates') {
        await pending[1]!.fulfill({ status: 500 });
        const failed = page.locator('.duplicate-image').nth(1);
        await expect(failed.getByText('图片加载失败')).toBeVisible();
        await expect.poll(() => failed.locator('img').evaluate((el: HTMLImageElement) => el.naturalWidth)).toBe(160);
      }
    });
  }
}
