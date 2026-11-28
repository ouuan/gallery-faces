import { test, expect } from "@playwright/test";

test('admin sections share one navigation across viewport changes and history', async ({ page }) => {
  await page.route('**/api/v1/**', route => route.fulfill({
    json: /\/(session|site)$/.test(new URL(route.request().url()).pathname) ? {} : [],
  }));
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto('/admin/duplicates');
  const navigation = page.getByRole('navigation', { name: '管理页面' });
  const current = navigation.getByRole('link', { name: '重复图片', exact: true });
  const logout = navigation.getByRole('button', { name: '退出登录' });
  const trigger = page.getByRole('button', { name: '管理菜单：重复图片' });
  const headerHome = page.getByRole('banner').getByRole('link', { name: 'Gallery Faces' });
  for (const [width, height] of [[320, 740], [844, 390], [1280, 900], [390, 844]]) {
    await page.setViewportSize({ width, height });
    if (width <= 720) {
      await expect(navigation).toBeHidden();
      await expect(page.getByRole('link', { name: '管理', exact: true })).toBeHidden();
      await expect(headerHome).toBeHidden();
      await trigger.click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect.poll(async () => (await page.getByRole('dialog').boundingBox())?.x).toBe(0);
      await expect(navigation.getByRole('link').first()).toHaveAccessibleName('图库');
    } else {
      await expect(trigger).toBeHidden();
      await expect(headerHome).toBeVisible();
    }
    await expect(current).toHaveAttribute('aria-current', 'page');
    await expect(current).toBeInViewport({ ratio: 1 });
    await expect(logout).toBeInViewport({ ratio: 1 });
    if (height > 600) {
      const bottomInset = await navigation.evaluate(nav => nav.getBoundingClientRect().bottom - nav.querySelector('button')!.getBoundingClientRect().bottom);
      expect(bottomInset).toBeCloseTo(await navigation.evaluate(nav => parseFloat(getComputedStyle(nav).paddingBottom)), 0);
    }
    await expect(navigation.getByRole('link')).toHaveCount(width <= 720 ? 9 : 8);
    await expect(navigation.getByRole('combobox')).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    if (width === 320) {
      await page.keyboard.press('Escape');
      await expect(navigation).toBeHidden();
      await expect(trigger).toBeFocused();
    } else if (width === 1280) {
      await navigation.getByRole('link', { name: '导入任务' }).click();
      await expect(page.getByRole('heading', { name: '导入任务', exact: true })).toBeVisible();
      await expect(logout).toBeInViewport({ ratio: 1 });
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await expect(logout).toBeInViewport({ ratio: 1 });
      await page.goBack();
      await expect(current).toHaveAttribute('aria-current', 'page');
    }
  }
  await page.screenshot({ path: '/tmp/gallery-faces/admin-drawer-390.png' });
  const importLink = navigation.getByRole('link', { name: '导入任务' });
  await importLink.click();
  await expect(page.getByRole('button', { name: '管理菜单：导入任务' })).toBeVisible();
  await expect(navigation).toBeHidden();
  await page.goBack();
  await trigger.click();
  await expect(current).toHaveAttribute('aria-current', 'page');
  await expect(current).toBeInViewport({ ratio: 1 });
  await navigation.getByRole('link', { name: '图库' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(headerHome).toBeHidden();
  await expect(page.getByRole('button', { name: '图库菜单：Gallery Faces' })).toHaveText('Gallery Faces');
});

test("photo management link requires a session and opens the displayed image", async ({ page }) => {
  let admin = false;
  const source = { id: 1, post_id: 1, platform: "x", author: "fixture", published_at: "2026-01-01", url: "https://x.com/fixture/status/1" };
  // The public group ID differs from the image ID.
  const photo = { id: 7, image_id: 501, image_url: "/api/v1/media/by-hash/image/abc", thumbnail_url: "/api/v1/media/by-hash/thumbnail/def", download_url: "/api/v1/media/by-hash/original/ghi", width: 800, height: 600, people: [], source_count: 1, matched_source: source, sources: [source] };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/session")) return route.fulfill({ status: admin ? 200 : 401, json: admin ? { admin: true } : {} });
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith("/site")) return route.fulfill({ json: {} });
    if (path.endsWith("/gallery")) return route.fulfill({ json: { items: [photo], next_cursor: null } });
    if (path.endsWith("/gallery/7")) return route.fulfill({ json: photo });
    if (path.endsWith("/admin/images")) {
      expect(url.searchParams.get("image_id")).toBe("501");
      expect(url.searchParams.get("state")).toBe("all");
      return route.fulfill({ json: [{ id: 501, width: 800, height: 600, faces: [], sources: [source] }] });
    }
    return route.fulfill({ json: path.endsWith("/settings") ? {} : [] });
  });
  await page.goto("/?photo=7");
  await expect(page.getByRole("dialog", { name: "照片详情" })).toBeVisible();
  await expect(page.getByRole("link", { name: "管理此图片" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "审核重复图片" })).toHaveCount(0);
  await expect(page.locator('.photo-card img')).toHaveAttribute('src', photo.thumbnail_url);
  await expect.poll(() => page.locator('.detail-image img').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(800);
  await expect(page.getByRole('link', { name: '下载原图' })).toHaveAttribute('href', photo.download_url);
  admin = true;
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    const link = page.getByRole("link", { name: "管理此图片" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/admin/review?state=image&image=501");
    await expect(page.getByRole("link", { name: "审核重复图片" })).toHaveAttribute("href", "/admin/duplicates?image=501");
    await page.screenshot({ path: `/tmp/gallery-faces/admin-link-${width}.png` });
  }
  await page.getByRole("link", { name: "审核重复图片" }).click();
  await expect(page.getByText("图片 #501 及同组版本")).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("dialog", { name: "照片详情" })).toBeVisible();
  await page.getByRole("link", { name: "管理此图片" }).click();
  await expect(page).toHaveURL(/\/admin\/review\?state=image&image=501$/);
  await expect(page.getByRole("button", { name: "审核图片（501，共 1 个版本）", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "审核图片（501，共 1 个版本）", exact: true })).toBeVisible();
});
