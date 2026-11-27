import { test, expect } from "@playwright/test";

test("task pages preserve selection when polling and retrying, and reset after import", async ({ page }) => {
  const tasks = Array.from({ length: 45 }, (_, i) => ({
    id: 45 - i, kind: "import", payload: '{"directory":"分页测试目录"}',
    status: "failed", stage: "导入失败", done: 0, total: 1, speed: 0,
  }));
  let failNext = false;
  const requestedPages: number[] = [];
  await page.clock.install();
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/tasks")) {
      const current = Number(url.searchParams.get("page"));
      const size = Number(url.searchParams.get("page_size"));
      requestedPages.push(current);
      expect(size).toBe(20);
      if (failNext) {
        failNext = false;
        return route.fulfill({ status: 503, json: { detail: "测试网络错误" } });
      }
      return route.fulfill({ json: {
        items: tasks.slice((current - 1) * size, current * size),
        total: tasks.length, page: current, page_size: size,
      } });
    }
    if (path.endsWith("/retry")) {
      const id = Number(path.split("/").at(-2));
      tasks.find((task) => task.id === id)!.status = "queued";
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/import")) {
      tasks.unshift({ ...tasks[0], id: 46, status: "queued" });
      return route.fulfill({ json: [{ value: "test", status: "queued" }] });
    }
    if (path.endsWith("/session")) return route.fulfill({ json: { ok: true } });
    if (path.endsWith("/site") || path.endsWith("/settings"))
      return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/admin/import");
  const rows = page.locator(".task-table tbody tr");
  const pagination = page.getByRole("navigation", { name: "任务记录分页" });
  const previous = pagination.getByRole("button", { name: "上一页" });
  const next = pagination.getByRole("button", { name: "下一页" });
  const currentPage = pagination.locator('[aria-current="page"]');
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toContainText("#45");
  await expect(previous).toBeDisabled();
  await pagination.getByRole("button", { name: "第 2 页" }).press("Enter");
  await expect(rows.first()).toContainText("#25");
  await expect(currentPage).toHaveText("2");

  const beforePoll = requestedPages.length;
  await page.clock.fastForward(3000);
  await expect.poll(() => requestedPages.length).toBeGreaterThan(beforePoll);
  expect(requestedPages.at(-1)).toBe(2);
  await rows.first().getByRole("button", { name: "重试" }).click();
  await expect(rows.first().getByRole("button", { name: "取消" })).toBeVisible();
  await expect(currentPage).toHaveText("2");

  failNext = true;
  await next.click();
  await expect(page.getByText("测试网络错误")).toBeVisible();
  await expect(currentPage).toHaveText("2");
  await page.getByRole("button", { name: "重新加载" }).click();
  await expect(rows).toHaveCount(5);
  await expect(rows.first()).toContainText("#5");
  await expect(next).toBeDisabled();
  await expect(page.getByText("任务记录加载失败")).toHaveCount(0);

  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await pagination.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await previous.click();
  await expect(currentPage).toHaveText("2");
  await page.locator(".import-form textarea").fill("https://x.com/test/status/1");
  await page.getByRole("button", { name: "创建导入任务" }).click();
  await expect(rows.first()).toContainText("#46");
  await expect(currentPage).toHaveText("1");
  await expect(pagination).toContainText("共 46 条");
});
