import { test, expect } from "@playwright/test";

test("sections load only required resources and review refresh retains feedback", async ({ page }) => {
  const counts: Record<string, number> = {};
  const actions: any[] = [];
  const images = [1, 2].map(id => ({ id, width: 800, height: 600, faces: [], sources: [], detection: "done" }));
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    counts[path] = (counts[path] || 0) + 1;
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (path === "/session") return route.fulfill({ json: { admin: true } });
    if (path === "/site") return route.fulfill({ json: { timezone: "UTC" } });
    if (path === "/admin/images") return route.fulfill({ json: images });
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === "/admin/images/actions") {
      actions.push(route.request().postDataJSON());
      return route.fulfill({ json: { ok: true } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review");
  await expect(page.getByRole("button", { name: "全选", exact: true })).toBeEnabled();
  expect(counts["/site"]).toBe(1);
  expect(counts["/people"]).toBe(1);
  expect(counts["/groups"]).toBe(1);
  for (const path of ["/admin/settings", "/admin/tasks", "/admin/directories", "/admin/duplicates"])
    expect(counts[path] || 0).toBe(0);
  await page.getByRole("checkbox", { name: "选择图片 1", exact: true }).check();
  await page.getByRole("button", { name: "全选", exact: true }).click();
  await expect(page.getByText("已选 2 张", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "取消全选", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "选择图片 1", exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "全选", exact: true }).click();
  await page.getByRole("button", { name: "隐藏", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认", exact: true }).click();
  await expect.poll(() => actions).toEqual([{ action: "hide", ids: [1, 2] }]);
  await expect(page.getByText("当前图片 #1", { exact: true })).toBeVisible();
  expect(counts["/admin/images/1/feedback"]).toBe(1);
});

test("all sources render once and legacy source changes do not reload details", async ({ page }) => {
  let details = 0;
  const source = { id: 1, platform: "x", author: "fixture", published_at: "2026-01-01T01:02:00Z", url: "https://x.com/fixture/status/1", images: [{ image_id: 1, width: 800, height: 600 }, { image_id: 2, width: 800, height: 600 }] };
  const photo = { id: 1, image_id: 1, width: 800, height: 600, people: [], source_count: 2, matched_source: source, sources: [source, { ...source, id: 2, images: [{ image_id: 3, width: 1200, height: 900 }] }] };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/gallery/1")) { details++; return route.fulfill({ json: photo }); }
    if (path.endsWith("/gallery")) return route.fulfill({ json: { items: [photo], next_cursor: null } });
    if (path.endsWith("/site")) return route.fulfill({ json: { timezone: "UTC" } });
    if (path.endsWith("/session")) return route.fulfill({ status: 401, json: {} });
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    return route.fulfill({ json: [] });
  });
  await page.goto("/?photo=1&source=99");
  const sources = page.locator(".source-block");
  await expect(sources).toHaveCount(2);
  await expect(sources.first()).toContainText("01:02");
  await expect(sources.first().locator(".source-resolution > span:last-child")).toHaveText("800 × 600");
  await expect(sources.last().locator(".source-resolution > span:last-child")).toHaveText("1200 × 900");
  await expect(sources.getByRole("link", { name: "X · fixture", exact: true })).toHaveCount(2);
  await expect(sources.first().getByRole("link", { name: "X · fixture", exact: true })).toHaveAttribute("href", source.url);
  await expect(page.getByRole("link", { name: "打开帖子" })).toHaveCount(0);
  await page.evaluate(() => { history.pushState({}, "", "/?photo=1&source=1"); dispatchEvent(new PopStateEvent("popstate")); });
  await expect(sources).toHaveCount(2);
  expect(details).toBe(1);
  for (const width of [320, 390, 768, 900, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
      expect(await page.locator(".lightbox").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      await page.screenshot({ path: `/tmp/gallery-faces/sources-${width}-${theme}.png` });
    }
  }
  photo.source_count = 1;
  photo.sources = [source];
  source.images.push({ image_id: 4, width: 1600, height: 1200 });
  await page.reload();
  await expect(sources).toHaveCount(1);
  await expect(sources.locator(".source-resolution > span:last-child")).toHaveText("800 × 600、1600 × 1200");
  source.images = [];
  await page.reload();
  await expect(sources.locator(".source-resolution")).toHaveCount(0);
  await expect(sources.getByRole("link", { name: "X · fixture", exact: true })).toBeVisible();
});

test("task polling pauses when hidden and does not overlap slow requests", async ({ page }) => {
  let taskRequests = 0;
  let release: (() => void) | undefined;
  await page.clock.install();
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/tasks")) {
      taskRequests++;
      if (taskRequests === 2) await new Promise<void>(resolve => release = resolve);
      return route.fulfill({ json: { items: [], total: 0, page: 1 } });
    }
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    return route.fulfill({ json: path.endsWith("/site") ? {} : [] });
  });
  await page.goto("/admin/import");
  await expect(page.getByRole("heading", { name: "导入任务", exact: true })).toBeVisible();
  expect(taskRequests).toBe(1);
  await page.clock.runFor(3000);
  await expect.poll(() => taskRequests).toBe(2);
  await page.clock.runFor(9000);
  expect(taskRequests).toBe(2);
  release!();
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.runFor(9000);
  expect(taskRequests).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => taskRequests).toBe(3);
});
