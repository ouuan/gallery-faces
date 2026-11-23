import { expect, test } from '@playwright/test';

test.use({ hasTouch: true });

for (const width of [390, 1280]) {
  test(`photo zoom and pan keep their anchor at ${width}px`, async ({ page }) => {
    const source = { id: 1, platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/1' };
    const photos = [1, 2].map(id => ({ id, image_id: id, people: [], sources: [source], matched_source: source, source_count: 1,
      width: 800, height: 600, image_url: '/api/v1/media/photo', thumbnail_url: '/api/v1/media/photo' }));
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/media/photo')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
      if (path.endsWith('/gallery')) return route.fulfill({ json: { items: photos, next_cursor: null } });
      if (path.includes('/gallery/')) return route.fulfill({ json: photos[Number(path.split('/').pop()) - 1] });
      return route.fulfill({ json: path.endsWith('/feedback') ? { items: [] } : /\/(session|site)$/.test(path) ? {} : [] });
    });
    await page.goto('/?photo=1');
    const image = page.locator('.detail-image img');
    const zoomIn = page.getByRole('button', { name: '放大', exact: true });
    const zoomOut = page.getByRole('button', { name: '缩小', exact: true });
    await expect(image).toHaveAttribute('src', /^blob:/);
    await expect(image).toBeVisible();
    const fit = (await image.boundingBox())!;
    const x = fit.x + fit.width * 0.6, y = fit.y + fit.height * 0.55;
    await page.touchscreen.tap(x, y);
    await expect(zoomOut).toBeDisabled();
    await page.touchscreen.tap(x, y);
    await expect(zoomOut).toBeEnabled();
    expect((await image.boundingBox())!.width).toBeCloseTo(fit.width * 2, 0);
    await page.touchscreen.tap(x + 50, y);
    await expect(zoomOut).toBeEnabled();
    await page.touchscreen.tap(x + 50, y);
    await expect(zoomOut).toBeDisabled();
    await page.mouse.move(x, y);
    await page.mouse.wheel(0, -1000);
    await expect(zoomIn).toBeDisabled();
    const enlarged = (await image.boundingBox())!;
    expect(enlarged.width).toBeCloseTo(fit.width * 3, 0);
    expect(Math.abs(enlarged.x + enlarged.width * 0.6 - x)).toBeLessThan(1);
    expect(Math.abs(enlarged.y + enlarged.height * 0.55 - y)).toBeLessThan(1);
    await page.mouse.down();
    await page.mouse.move(x + 40, y + 30);
    await page.mouse.up();
    const dragged = (await image.boundingBox())!;
    expect(dragged.x - enlarged.x).toBe(40);
    expect(dragged.y - enlarged.y).toBe(30);
    await page.mouse.dblclick(x, y);
    await expect(zoomOut).toBeDisabled();
    expect(await image.boundingBox()).toEqual(fit);
    await page.mouse.click(x, y);
    await expect(zoomOut).toBeEnabled();
    const clicked = (await image.boundingBox())!;
    expect(clicked.width).toBeCloseTo(fit.width * 2, 0);
    expect(Math.abs(clicked.x + clicked.width * 0.6 - x)).toBeLessThan(1);
    await page.getByRole('button', { name: '下一张' }).click();
    await expect(image).toHaveAttribute('src', /^blob:/);
    await expect(zoomOut).toBeDisabled();
    expect(await image.boundingBox()).toEqual(fit);
    await page.mouse.dblclick(x, y);
    await expect(zoomOut).toBeEnabled();
  });
}
