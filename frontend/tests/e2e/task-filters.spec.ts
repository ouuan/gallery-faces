import { test, expect } from "@playwright/test";

test("task filters combine multiple values and survive polling, actions, errors and import", async ({ page }) => {
  const tasks = Array.from({ length: 85 }, (_, i) => ({
    id: 85 - i, kind: i % 2 ? "download" : "import", payload: "{}",
    status: i % 3 ? "failed" : "queued", stage: "等待处理", done: 0, total: 1, speed: 0,
  }));
  const queries: URLSearchParams[] = [];
  let failNext = false;
  let release: (() => void) | undefined;
  let delayNext = false;
  await page.clock.install();
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/tasks")) {
      const q = url.searchParams;
      queries.push(q);
      if (failNext && q.get("page") === "2") {
        failNext = false;
        return route.fulfill({ status: 503, json: { detail: "测试网络错误" } });
      }
      const filtered = tasks.filter(t => (!q.has("kind") || q.getAll("kind").includes(t.kind))
        && (!q.has("status") || q.getAll("status").includes(t.status)));
      const current = Math.min(Number(q.get("page")), Math.max(1, Math.ceil(filtered.length / 20)));
      const data = { items: filtered.slice((current - 1) * 20, current * 20), total: filtered.length, page: current, page_size: 20 };
      if (delayNext) {
        delayNext = false;
        await new Promise<void>(resolve => { release = resolve; });
      }
      return route.fulfill({ json: data });
    }
    if (path.endsWith("/retry") || path.endsWith("/cancel")) {
      tasks.find(t => t.id === Number(path.split("/").at(-2)))!.status = path.endsWith("/retry") ? "queued" : "cancelled";
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/import")) return route.fulfill({ json: [{ value: "test", status: "queued" }] });
    if (path.endsWith("/session") || path.endsWith("/site") || path.endsWith("/settings")) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/import");
  const rows = page.locator(".task-table tbody tr");
  const pagination = page.getByRole("navigation", { name: "任务记录分页" });
  const currentPage = pagination.locator('[aria-current="page"]');
  const select = async (name: string, label: string) => {
    await page.getByRole("group", { name, exact: true }).click();
    await page.locator(".n-base-select-option").filter({ hasText: label }).click();
    await page.keyboard.press("Escape");
  };
  await expect(rows).toHaveCount(20);
  await pagination.getByRole("button", { name: "下一页" }).click();
  await expect(currentPage).toHaveText("2");
  await select("任务类型", "目录导入");
  await expect(currentPage).toHaveText("1");
  await select("任务类型", "链接下载");
  await select("任务状态", "失败");
  await select("任务状态", "排队中");
  await expect.poll(() => queries.at(-1)!.getAll("status")).toEqual(["failed", "queued"]);
  const count = queries.length;
  await page.clock.fastForward(3000);
  await expect.poll(() => queries.length).toBeGreaterThan(count);
  expect(queries.at(-1)!.getAll("kind")).toEqual(["import", "download"]);
  const cancelledId = await rows.first().innerText();
  await rows.first().getByRole("button", { name: "取消" }).click();
  await expect(rows.first()).not.toHaveText(cancelledId);
  await select("任务状态", "排队中"); // deselect, leaving failed only
  const retriedId = await rows.first().innerText();
  await rows.first().getByRole("button", { name: "重试" }).click();
  await expect(rows.first()).not.toHaveText(retriedId);
  await expect(rows).toHaveCount(20);
  await expect(page.getByText("正在加载任务记录…")).toHaveCount(0);
  failNext = true;
  await pagination.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("测试网络错误")).toBeVisible();
  await page.getByRole("button", { name: "重新加载" }).click();
  await expect(currentPage).toHaveText("2");
  expect(queries.at(-1)!.getAll("status")).toEqual(["failed"]);
  await page.locator(".import-form textarea").fill("https://x.com/test/status/1");
  await page.getByRole("button", { name: "创建导入任务" }).click();
  await expect(currentPage).toHaveText("1");
  expect(queries.at(-1)!.getAll("status")).toEqual(["failed"]);

  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme });
      await page.clock.runFor(500);
      await page.locator(".task-filters").scrollIntoViewIfNeeded();
      await page.screenshot({ animations: "disabled", path: `/tmp/gallery-faces/task-filters-${width}-${colorScheme}.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }

  delayNext = true;
  await select("任务类型", "人脸检测");
  await expect.poll(() => !!release).toBe(true);
  await page.locator(".task-filters").getByRole("button", { name: "清空筛选" }).click();
  await expect(pagination).toContainText("共 85 条");
  release!();
  await page.clock.runFor(100);
  await expect(pagination).toContainText("共 85 条");
  await select("任务类型", "人脸检测");
  await expect(page.getByText("没有符合筛选条件的任务")).toBeVisible();
  await expect(pagination).toHaveCount(0);
  await page.reload();
  await expect(rows).toHaveCount(20);
  expect(queries.at(-1)!.has("kind")).toBe(false);
  await page.getByRole("group", { name: "任务类型", exact: true }).locator('[tabindex="0"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "任务类型", exact: true })).toBeFocused();
  await page.keyboard.insertText("人脸检测");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape");
  await expect(page.getByText("没有符合筛选条件的任务")).toBeVisible();
});
