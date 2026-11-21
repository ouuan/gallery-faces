import { expect, test } from '@playwright/test';

test('cache monitoring is read-only and refresh preserves settings edits', async ({ page }) => {
  let refreshed = false;
  const gib = 2 ** 30;
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session')) return route.fulfill({ json: { admin: true } });
    if (path.endsWith('/site')) return route.fulfill({ json: { site_title: 'Gallery' } });
    if (path.endsWith('/admin/settings')) return route.fulfill({ json: { site_title: 'Gallery', cookies: {}, models_ready: true, threshold: 0.5, margin: 0.1, phash_distance: 4, aspect_tolerance: 0.01, detection_threshold: 0.5, ssim_threshold: 0.98 } });
    if (path.endsWith('/admin/media-cache')) {
      expect(route.request().method()).toBe('GET');
      return route.fulfill({ json: {
        config: { reported_at: 1760000000, low_bytes: 5 * gib, target_bytes: 10 * gib },
        activity_24h: [{ folder: 'images', hits: refreshed ? 9 : 3, misses: 1, recoveries: 1 }, { folder: 'originals', hits: 0, misses: refreshed ? 1 : 0, recoveries: 0 }],
        inventory: [{ folder: 'images', present: refreshed ? 81 : 80, evicted: refreshed ? 19 : 20, lost: 0, missing: 0, unknown: 0 }, { folder: 'originals', present: 94, evicted: 3, lost: 2, missing: 1, unknown: 0 }],
        volumes: [{ folders: ['data', 'images'], free_bytes: 12 * gib, last_cleanup: { finished_at: 1760000000, before_bytes: 4 * gib, after_bytes: 10 * gib, target_bytes: 10 * gib, outcome: 'target', removals: { images: { count: 20, min_idle_days: 8.25, min_score: 33 } } } }, { folders: ['originals'], free_bytes: 20 * gib, last_cleanup: null }],
      } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/admin/settings');
  const panel = page.getByRole('region', { name: '图片磁盘缓存' });
  await expect(panel.getByRole('columnheader', { name: '已丢失' })).toBeVisible();
  const inventory = panel.getByRole('table', { name: /当前文件数/ });
  await expect(inventory.getByRole('row', { name: /原图/ }).getByRole('cell', { name: '2', exact: true })).toBeVisible();
  const activity = panel.getByRole('table', { name: '源站缓存读取（最近 24 小时）' });
  await expect(activity.getByRole('row', { name: /展示图/ })).toHaveText('展示图75%311');
  await expect(activity.getByText('暂无读取')).toBeVisible();
  await expect(panel.getByText('8.25 天')).toBeVisible();
  await expect(panel.getByText('暂无清理记录。')).toBeVisible();
  const input = page.getByRole('textbox', { name: '人脸检测阈值' });
  await input.fill('0.3');
  refreshed = true;
  await panel.getByRole('button', { name: '刷新状态' }).click();
  await expect(panel.getByRole('cell', { name: '81', exact: true })).toBeVisible();
  await expect(activity.getByRole('cell', { name: '90%', exact: true })).toBeVisible();
  await expect(activity.getByRole('cell', { name: '0%', exact: true })).toBeVisible();
  await expect(input).toHaveValue('0.3');
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await panel.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await panel.screenshot({ path: `/tmp/gallery-faces/cache-settings-${width}.png` });
  }
});
