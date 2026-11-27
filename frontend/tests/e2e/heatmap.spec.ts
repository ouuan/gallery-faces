import { expect, test, type Page } from '@playwright/test';

test.use({ timezoneId: 'America/New_York' });
const bounds = 'start=2024-02-29T05:00:00Z&end=2026-03-09T04:00:00Z';
async function fixture(page: Page) {
  const requests: URL[] = [];
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/heatmap')) {
      requests.push(url);
      return route.fulfill({ json: [
        { date: '2024-02-29', new_photos: 4, posts: 1 }, { date: '2026-03-06', new_photos: 20, posts: 1 },
        { date: '2026-03-07', new_photos: 4, posts: 1 }, { date: '2026-03-08', new_photos: 0, posts: 2 },
      ] });
    }
    if (url.pathname.endsWith('/site')) return route.fulfill({ json: { site_title: '照片库' } });
    if (url.pathname.endsWith('/gallery')) return route.fulfill({ json: { items: [], total: 0, next_cursor: null } });
    return route.fulfill({ json: [] });
  });
  return requests;
}

test('inherits gallery filters, includes empty years, and opens the selected local day', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const requests = await fixture(page);
  await page.goto(`/?${bounds}&publishers=x:alice`);
  await page.getByRole('link', { name: '热力图' }).click();
  await expect(page.locator('.heat-year h2')).toHaveText(['2026 年', '2025 年', '2024 年']);
  expect(requests[0].searchParams.get('timezone')).toBe('America/New_York');
  await expect(page.locator('.heat-year .n-heatmap-color-indicator')).toHaveCount(0);
  const colorOn = (date: string) => page.locator(`[data-date="${date}"]`).evaluate(cell => getComputedStyle(cell).backgroundColor);
  const legend = page.getByRole('group', { name: '新照片数图例' });
  await expect(legend.locator('span')).toHaveText(['0', '1–10', '11–20']);
  expect(await colorOn('2024-02-29')).toBe(await colorOn('2026-03-07'));
  expect(await colorOn('2024-02-29')).not.toBe(await colorOn('2026-03-06'));
  expect(await colorOn('2024-02-29')).toBe(await legend.locator('i').nth(1).evaluate(cell => getComputedStyle(cell).backgroundColor));
  const year = page.getByRole('region', { name: '2026 年' });
  const day = year.getByRole('button', { name: '2026-03-08，0 张新照片，2 条帖子' });
  const background = () => day.evaluate(element => getComputedStyle(element).backgroundColor);
  const before = await background();
  await page.getByRole('radiogroup', { name: '统计指标' }).getByText('帖子', { exact: true }).click();
  await expect(page.getByRole('radio', { name: '帖子', exact: true })).toBeChecked();
  await expect(page.getByRole('group', { name: '帖子数图例' }).locator('span')).toHaveText(['0', '1', '2']);
  await expect.poll(background).not.toBe(before);
  expect(requests).toHaveLength(1);
  await year.locator('[data-date="2026-03-07"]').focus();
  await page.keyboard.press('ArrowDown');
  await expect(day).toBeFocused();
  await page.keyboard.press('Enter');
  await page.keyboard.press('Tab');
  const link = year.getByRole('link', { name: '查看图库' });
  await expect(link).toBeFocused();
  await link.press('Enter');
  await expect(page).toHaveURL(url => url.pathname === '/' && url.searchParams.get('publishers') === 'x:alice'
    && Date.parse(url.searchParams.get('start')!) === Date.parse('2026-03-08T05:00:00Z')
    && Date.parse(url.searchParams.get('end')!) === Date.parse('2026-03-09T04:00:00Z'));
  await page.goBack();
  const checkbox = page.locator('.desktop-filters').getByRole('checkbox', { name: '包含无人脸图片' });
  await checkbox.check();
  await expect(page).toHaveURL(/include_no_faces=true/);
  await page.reload();
  await expect(checkbox).toBeChecked();
  await page.goBack();
  await expect(checkbox).not.toBeChecked();
});

test('mobile drawer applies filters and a day can be selected without page overflow', async ({ page }) => {
  await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/heatmap?${bounds}`);
  await page.getByRole('button', { name: '筛选', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '筛选照片' });
  await drawer.getByRole('checkbox', { name: '包含无人脸图片' }).check();
  await drawer.getByRole('button', { name: '应用筛选' }).click();
  await expect(page).toHaveURL(/include_no_faces=true/);
  const year = page.getByRole('region', { name: '2024 年' });
  await year.getByRole('button', { name: '2024-02-29，4 张新照片，1 条帖子' }).click();
  await expect(year.getByRole('link', { name: '查看图库' })).toHaveAttribute('href', /include_no_faces=true/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await year.locator('.year-scroll').evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
});

test('outside clicks clear the pinned day without swallowing the gallery link', async ({ page }) => {
  await fixture(page);
  await page.goto(`/heatmap?${bounds}`);
  const firstYear = page.getByRole('region', { name: '2026 年' });
  const firstDay = firstYear.locator('[data-date="2026-03-08"]');
  const secondYear = page.getByRole('region', { name: '2024 年' });
  const secondDay = secondYear.locator('[data-date="2024-02-29"]');
  await firstDay.click();
  await expect(firstDay).toHaveAttribute('aria-pressed', 'true');
  await firstYear.getByRole('heading').click();
  await expect(firstDay).toHaveAttribute('aria-pressed', 'false');
  await expect(firstYear.getByText('全年合计')).toBeVisible();
  await expect(firstYear.getByRole('link', { name: '查看图库' })).toHaveCount(0);
  await firstDay.click();
  await secondDay.click();
  await expect(firstDay).toHaveAttribute('aria-pressed', 'false');
  await expect(secondDay).toHaveAttribute('aria-pressed', 'true');
  await secondYear.getByRole('link', { name: '查看图库' }).click();
  await expect(page).toHaveURL(url => url.pathname === '/' && url.searchParams.get('start')?.startsWith('2024-02-29') === true);
});
