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
    started_at: i === 2 ? null : "2026-11-18T01:05:00Z",
    round_started_at: i >= 3 ? "2026-11-18T01:42:00Z" : null,
    elapsed_seconds: i === 2 ? null : 389,
    round_seconds: i === 4 ? 121 : null,
    result: i === 0 ? '{"imported":3,"skipped_existing":2,"skipped_trashed":1}' : '{}',
    error: i === 1 ? '下载失败\n' + '错误详情'.repeat(100) : null,
    finished_at: i < 3 ? "2026-11-18T02:03:00Z" : null,
  }));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith("/tasks")
      ? { items, total: items.length, page: 1 }
      : path.endsWith("/session") || path.endsWith("/site") ? {} : [] });
  });
  await page.goto("/admin/import");
  const rows = page.locator(".task-table tbody");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(0)).toContainText('新入库 3 张 · 跳过 3 张');
  await expect(rows.nth(0)).toContainText('已运行 6 分 29 秒');
  await expect(rows.nth(2)).not.toContainText('已运行');
  await expect(rows.nth(3)).toContainText('累计 6 分 29 秒');
  await expect(rows.nth(4)).toContainText('本轮 2 分 1 秒');
  await expect(rows.nth(4)).toContainText('累计 6 分 29 秒');
  const ranges = ['2026/11/18 00:00:00 至 2026/11/19 00:00:00（不含）', '自 2026/11/18 00:00:00 起', '截至 2026/11/19 00:00:00（不含）'];
  for (const [i, label] of ["完成时间", "失败时间", "取消时间"].entries()) {
    await rows.nth(i).getByRole('button', { name: /展开任务/ }).press('Enter');
    await expect(rows.nth(i)).toContainText(label + "：2026/11/18 10:03");
    await expect(rows.nth(i)).toContainText("创建时间：2026/11/18 09:02");
    await expect(rows.nth(i)).toContainText('下载范围：' + ranges[i]);
    await rows.nth(i).getByRole('button', { name: /收起任务/ }).press('Enter');
  }
  await expect(rows.nth(3)).not.toContainText("下载范围");
  await expect(rows.nth(3)).toContainText("等待下一轮 · 第 3 轮");
  await expect(rows.nth(4)).not.toContainText("下载范围");
  await rows.nth(4).getByRole('button', { name: /展开任务/ }).click();
  await expect(rows.nth(4)).toContainText('任务开始：2026/11/18 09:05:00');
  await expect(rows.nth(4)).toContainText('第 4 轮开始：2026/11/18 09:42:00');
  await rows.nth(4).getByRole('button', { name: /收起任务/ }).click();
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
