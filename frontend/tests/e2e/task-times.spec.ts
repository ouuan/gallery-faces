import { test, expect } from "@playwright/test";

test.use({ timezoneId: "Asia/Shanghai" });

test("task records show creation and available finish times and download bounds", async ({ page }) => {
  const items = ["done", "failed", "cancelled", "queued", "running"].map((status, i) => ({
    id: i + 1, kind: "download", status, stage: status === "queued" ? "等待下一轮" : status, rounds: i, done: 0, total: 1, speed: 0,
    payload: JSON.stringify({
      url: "https://x.com/example",
      start: i === 0 || i === 1 ? "2026-11-17T16:00:00Z" : null,
      end: i === 0 || i === 2 ? "2026-11-18T16:00:00Z" : null,
    }),
    created_at: "2026-11-18T01:02:00Z",
    finished_at: i < 3 ? "2026-11-18T02:03:00Z" : null,
  }));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith("/tasks")
      ? { items, total: items.length, page: 1 }
      : path.endsWith("/session") || path.endsWith("/site") ? {} : [] });
  });
  await page.goto("/admin/import");
  const rows = page.locator(".task-table tbody tr");
  await expect(rows).toHaveCount(5);
  for (const [i, label] of ["完成时间", "失败时间", "取消时间"].entries()) {
    await expect(rows.nth(i)).toContainText(label + "：2026/11/18 10:03");
    await expect(rows.nth(i)).toContainText("创建时间：2026/11/18 09:02");
  }
  await expect(rows.nth(0)).toContainText("下载范围：2026/11/18 00:00:00 至 2026/11/19 00:00:00（不含）");
  await expect(rows.nth(1)).toContainText("下载范围：自 2026/11/18 00:00:00 起");
  await expect(rows.nth(2)).toContainText("下载范围：截至 2026/11/19 00:00:00（不含）");
  await expect(rows.nth(3)).not.toContainText("下载范围");
  await expect(rows.nth(3)).toContainText("等待下一轮 · 第 3 轮");
  await expect(rows.nth(4)).not.toContainText("下载范围");
  await expect(rows.nth(3).locator("time")).toHaveCount(1);
  await expect(rows.nth(4).locator("time")).toHaveCount(1);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await page.locator(".task-table").scrollIntoViewIfNeeded();
      await page.screenshot({ path: "/tmp/gallery-faces/task-times-" + width + "-" + colorScheme + ".png" });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
});
