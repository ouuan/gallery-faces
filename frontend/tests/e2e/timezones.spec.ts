import { test, expect } from "@playwright/test";

for (const [zone, expected] of [["Asia/Shanghai", "2026/01/02 04:30"], ["America/New_York", "2026/01/01 15:30"]]) {
  test.describe(zone, () => {
    test.use({ timezoneId: zone });
    test("local display and explicit boundaries in all date forms", async ({ page }) => {
      const source = { id: 1, platform: "x", author: "alice", published_at: "2026-01-01T20:30:00Z", url: "https://x.com/alice/status/1" };
      const photo = { id: 1, image_id: 1, width: 800, height: 600, image_url: "/fixture.svg", thumbnail_url: "/fixture.svg", download_url: "/fixture.svg", people: [], source_count: 1, matched_source: source };
      await page.route("**/fixture.svg", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' }));
      await page.route("**/api/v1/**", route => {
        const url = new URL(route.request().url()), path = url.pathname;
        if (path.endsWith("/site")) return route.fulfill({ json: { timezone: "America/New_York" } });
        if (path.endsWith("/date-bounds")) return route.fulfill({ json: {
          timezone: "America/New_York", current_offset_seconds: -18000,
          start: url.searchParams.get("start") ? { utc: "2026-03-08T05:00:00Z", offset_seconds: -18000 } : null,
          end: url.searchParams.get("end") ? { utc: "2026-03-09T04:00:00Z", offset_seconds: -14400 } : null,
        } });
        if (path.endsWith("/gallery")) return route.fulfill({ json: { items: [photo], next_cursor: null } });
        if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
        if (path.endsWith("/people")) return route.fulfill({ json: [{ id: 1, name: "人物甲", groups: [], accounts: [{ platform: "x", username: "alice" }], reference_count: 0 }] });
        if (path.endsWith("/tasks")) return route.fulfill({ json: { items: [], total: 0, page: 1 } });
        return route.fulfill({ json: [] });
      });
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto("/");
      await expect(page.locator(".photo-card").first()).toContainText(expected);
      const filters = page.locator(".desktop-filters");
      await expect(filters).toContainText("当前按 UTC-5 计算");
      await filters.getByLabel("开始日期").fill("2026-03-08");
      await filters.getByLabel("结束日期").fill("2026-03-08");
      await expect(filters).toContainText("开始：当日 00:00（UTC-5）；结束：次日 00:00（UTC-4），不含该时刻");
      await page.screenshot({ path: `/tmp/gallery-faces/timezone-desktop-${zone.replaceAll("/", "-")}.png` });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole("button", { name: "筛选", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "筛选照片", exact: true })).toContainText("UTC-4");
      await page.screenshot({ path: "/tmp/gallery-faces/timezone-mobile.png" });
      await page.goto("/admin/import");
      const form = page.locator(".import-form");
      await expect(form).toContainText("当前按 UTC-5 计算");
      await form.getByLabel("开始日期").fill("2026-03-08");
      await form.getByLabel("结束日期（含当天）").fill("2026-03-08");
      await expect(form).toContainText("UTC-4");
      await page.screenshot({ path: "/tmp/gallery-faces/timezone-import.png" });
      await page.goto("/admin/people");
      await page.getByRole("checkbox", { name: "选择人物 人物甲" }).check();
      await page.getByRole("button", { name: "导入照片", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText("当前按 UTC-5 计算");
      await dialog.getByLabel("开始日期", { exact: true }).fill("2026-03-08");
      await dialog.getByLabel("结束日期（含当天）").fill("2026-03-08");
      await expect(dialog).toContainText("UTC-4");
      await page.emulateMedia({ colorScheme: "dark" });
      await page.screenshot({ path: "/tmp/gallery-faces/timezone-people.png" });
      await expect(page.locator("html")).toHaveJSProperty("scrollWidth", 390);
    });
  });
}
