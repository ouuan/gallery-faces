import { test, expect, type Request } from '@playwright/test';

for (const width of [1440, 390]) {
  for (const movement of ['jump', 'scrub'] as const) {
    test(`fast ${movement} to queue end at ${width}px with slow thumbnails`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const thumbnails: number[] = [], originals: number[] = [];
      let peak = 0, queueReads = 0, cancelled = 0;
      const pending = new Set<Request>();
      const completed: string[] = [];
      page.on('request', request => {
        if (!request.url().includes('thumbnail=true')) return;
        pending.add(request);
        peak = Math.max(peak, pending.size);
      });
      page.on('requestfinished', request => {
        if (pending.delete(request)) completed.push(request.url());
      });
      page.on('requestfailed', request => {
        if (pending.delete(request)) cancelled++;
      });
      await page.route('**/api/v1/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname.includes('/admin/media/')) {
          const id = Number(url.pathname.split('/').pop());
          if (url.searchParams.has('thumbnail')) {
            thumbnails.push(id);
            // Keep requests in flight while the user crosses several viewports.
            await new Promise(resolve => setTimeout(resolve, 250));
          } else originals.push(id);
          return route.fulfill({ contentType: 'image/svg+xml', body: `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/><text x="100" y="300" font-size="120">${id}</text></svg>` });
        }
        if (url.pathname.endsWith('/admin/images')) {
          queueReads++;
          return route.fulfill({ json: Array.from({ length: 200 }, (_, index) => ({
            id: index + 1, group_id: index + 1, width: 800, height: 600,
            faces: [], sources: [], detection: 'done',
          })) });
        }
        if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
        return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
      });
      await page.goto('/admin/review');
      const strip = page.locator('.review-strip');
      await expect.poll(() => thumbnails.length).toBeGreaterThan(0);
      // Do not wait for the initial thumbnails: drag while they are downloading.
      const started = Date.now();
      await strip.evaluate(async (element, movement) => {
        const end = element.scrollWidth - element.clientWidth;
        const positions = movement === 'jump' ? [1] : [0.2, 0.4, 0.7, 0.95, 0.6, 0.85, 1];
        for (const position of positions) {
          element.scrollLeft = end * position;
          // One scroll offset per rendered frame models a fast scrollbar scrub.
          await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        }
      }, movement);
      const last = strip.locator('img').last();
      await expect(last).toBeInViewport();
      await expect.poll(() => last.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(800);
      const elapsed = Date.now() - started;
      // Every thumbnail currently visible must finish, including the left edge.
      await expect.poll(() => strip.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        return Array.from(element.querySelectorAll('img')).filter(image => {
          const rect = image.getBoundingClientRect();
          return rect.right > bounds.left && rect.left < bounds.right;
        }).every(image => image.complete && image.naturalWidth > 0);
      })).toBe(true);
      const requestsAtEnd = thumbnails.length;
      await expect.poll(() => cancelled).toBeGreaterThan(0);
      // Browser cancellation events can lag an observer batch by one frame.
      expect(peak).toBeLessThanOrEqual(2 * (Math.ceil(width / 124) + 2));
      expect(requestsAtEnd).toBeLessThan(100);
      if (movement === 'jump') expect(requestsAtEnd).toBeLessThanOrEqual(2 * (Math.ceil(width / 124) + 1));
      await strip.getByRole('button', { name: '审核图片（200，共 1 个版本）', exact: true }).click();
      await expect(page.locator('.review-main > .review-heading h3')).toContainText('图片 #200');
      await expect.poll(() => page.locator('.face-box-editor img').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(800);
      await expect(page).toHaveURL(/image=200/);
      // Return to the beginning and end to check reuse after the rapid movement.
      await strip.evaluate(element => { element.scrollLeft = 0; });
      await expect(strip.locator('img').first()).toBeInViewport();
      await expect.poll(() => strip.locator('img').first().evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(800);
      await strip.evaluate(element => { element.scrollLeft = element.scrollWidth; });
      await expect(last).toBeInViewport();
      await page.waitForLoadState('networkidle');
      expect(completed.length).toBe(new Set(completed).size);
      expect(originals).toEqual([1, 200]);
      expect(queueReads).toBe(1);
      console.log(`${width}px ${movement}: ${requestsAtEnd}/200 thumbnails, ${cancelled} cancelled, peak ${peak} in flight, end image ready in ${elapsed}ms (250ms mocked thumbnail delay)`);
      await page.screenshot({ path: `/tmp/gallery-faces/review-fast-${movement}-${width}.png` });
    });
  }
}
