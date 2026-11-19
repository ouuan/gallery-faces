import { test, expect } from '@playwright/test';

test('refreshing review metadata preserves the loaded original', async ({ page }) => {
  let originals = 0;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/admin/media/')) {
      if (!url.searchParams.has('thumbnail')) originals++;
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    }
    if (url.pathname.endsWith('/admin/images')) return route.fulfill({ json: [{
      id: 1, width: 800, height: 600, faces: [], sources: [], detection: 'done',
    }] });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
  });
  await page.goto('/admin/review');
  const photo = page.locator('.face-box-editor img');
  await expect(photo).toBeVisible();
  const originalUrl = await photo.getAttribute('src');
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await expect(page.getByText('正在加载审核项目…')).toHaveCount(0);
    await expect(photo).toBeVisible();
  }
  console.log(`Original downloads after initial load + 3 metadata refreshes: ${originals}`);
  expect(originals).toBe(1);
  await expect(photo).toHaveAttribute('src', originalUrl!);
});

for (const queueSize of [200, 1]) test(`face confirmations refresh their group and refill an exhausted queue (${queueSize} groups)`, async ({ page }) => {
  const reads: { image: string | null; rows: number; bytes: number }[] = [];
  const faces = [1, 2, 3].map(id => ({ id, revision: 0, person_id: 7, locked: false, ignored: false,
    box: [id * 100, 100, 80, 80], candidates: [] }));
  const queue = Array.from({ length: queueSize }, (_, index) => ({ id: index + 1, group_id: index + 1,
    width: 800, height: 600, detection: 'done', faces: index === 0 ? faces : [], sources: [], member_ids: [index + 1] }));
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (/\/admin\/faces\/\d+$/.test(url.pathname)) {
      const face = faces.find(face => face.id === Number(url.pathname.split('/').pop()))!;
      Object.assign(face, route.request().postDataJSON(), { revision: face.revision + 1 });
      return route.fulfill({ json: face });
    }
    if (url.pathname.endsWith('/admin/images')) {
      const image = url.searchParams.get('image_id');
      const rows = queue.filter(row => (row.id !== 1 || faces.some(face => !face.locked)) && (!image || row.id === Number(image)));
      if (!image && !rows.length) rows.push({ ...queue[0], id: 201, group_id: 201, member_ids: [201], faces: [] });
      const body = JSON.stringify(rows);
      reads.push({ image, rows: rows.length, bytes: body.length });
      return route.fulfill({ contentType: 'application/json', body });
    }
    if (url.pathname.includes('/media/') || url.pathname.endsWith('/crop'))
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (url.pathname.endsWith('/people')) return route.fulfill({ json: [{ id: 7, name: '人物7', groups: [], accounts: [] }] });
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
  });
  await page.goto('/admin/review');
  for (let index = 0; index < 3; index++) {
    await page.locator('.face-review').nth(index).getByRole('button', { name: '确认', exact: true }).click();
    await expect.poll(() => reads.length).toBe(index + 2 + (queueSize === 1 && index === 2 ? 1 : 0));
    await expect(page.getByText('正在加载审核项目…')).toHaveCount(0);
  }
  if (queueSize === 200) {
    await expect(page.locator('.review-main > .review-heading h3')).toContainText('图片 #2');
    await expect(page.locator('.review-strip button')).toHaveCount(199);
    await page.getByRole('button', { name: '下一张', exact: true }).click();
    await expect(page.locator('.review-main > .review-heading h3')).toContainText('图片 #3');
  } else {
    await expect(page.locator('.review-main > .review-heading h3')).toContainText('图片 #201');
    await expect(page.locator('.review-strip button')).toHaveCount(1);
  }
  console.log(`Review response rows: ${reads.map(read => read.rows)}; mutation refresh bytes: ${reads.slice(1).reduce((sum, read) => sum + read.bytes, 0)}`);
  expect(reads.map(read => read.image)).toEqual(queueSize === 200 ? [null, '1', '1', '1'] : [null, '1', '1', '1', null]);
  expect(reads.map(read => read.rows)).toEqual(queueSize === 200 ? [200, 1, 1, 0] : [1, 1, 1, 0, 1]);
});

for (const width of [1440, 390]) test(`thumbnail request budget at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const thumbnails = new Set<number>();
  let thumbnailRequests = 0;
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/admin/media/')) {
      // The strip uses fetch; the editor also displays a thumbnail while its original loads.
      if (url.searchParams.has('thumbnail') && route.request().resourceType() === 'fetch') {
        thumbnailRequests++;
        thumbnails.add(Number(url.pathname.split('/').pop()));
      }
      return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    }
    if (url.pathname.endsWith('/admin/images')) return route.fulfill({ json: Array.from({ length: 200 }, (_, index) => ({
      id: index + 1, width: 800, height: 600, faces: [], sources: [], detection: 'done',
    })) });
    if (url.pathname.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: /\/(session|site)$/.test(url.pathname) ? {} : [] });
  });
  await page.goto('/admin/review');
  await expect(page.locator('.face-box-editor img')).toBeVisible();
  const strip = page.locator('.review-strip');
  const waitForStripThumbnails = () => expect.poll(() => strip.evaluate(element => {
    const bounds = element.getBoundingClientRect();
    // Include the observer's one-thumbnail preload margin before scrolling away.
    const visible = Array.from(element.querySelectorAll('img')).filter(image => {
      const rect = image.getBoundingClientRect();
      return rect.right >= bounds.left - 124 && rect.left <= bounds.right + 124;
    });
    return visible.length > 0 && visible.every(image => image.complete && image.naturalWidth === 800);
  })).toBe(true);
  await waitForStripThumbnails();
  const initial = thumbnails.size;
  console.log(`${width}px initial thumbnails: ${initial}/200`);
  expect(initial).toBeGreaterThan(0);
  expect(initial).toBeLessThanOrEqual(Math.ceil(width / 124) + 1);
  expect(thumbnails.has(200)).toBe(false);
  await page.screenshot({ path: `/tmp/gallery-faces/review-${width}.png` });
  await strip.evaluate(element => { element.scrollLeft = element.scrollWidth; });
  await expect.poll(() => thumbnails.has(200)).toBe(true);
  await waitForStripThumbnails();
  await strip.evaluate(element => { element.scrollLeft = 0; });
  await waitForStripThumbnails();
  const refreshed = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith('/admin/images') && response.ok());
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await refreshed;
  await expect(page.getByText('正在加载审核项目…')).toHaveCount(0);
  await waitForStripThumbnails();
  expect(thumbnailRequests).toBe(thumbnails.size);
});
