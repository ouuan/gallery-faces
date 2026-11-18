import { test, expect } from "@playwright/test";

const preview = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#8799aa"/></svg>';
const photo = (id: number) => ({
  id, group_id: 1, width: 1600, height: 1200, trashed_at: "2026-11-18T04:00:00Z",
  has_references: false, cleanup_pending: false, restore_task: null as null | { id: number; status: string; stage: string; error: string | null },
  faces: [{ id, person_id: 7, locked: 1, ignored: 0 }],
  sources: [{ id, platform: "x", author: "fixture", published_at: "2026-01-01T00:00:00Z", url: `https://x.com/fixture/status/${id}` }],
});

test("trash preserves read-only previews and supports cancellation, failure and selective restore", async ({ page }) => {
  page.on("pageerror", error => { throw error; });
  let images = [{ ...photo(11), has_references: true }, photo(12)];
  const restores: { action: string; ids: number[]; directory: string | null }[] = [];
  const media: string[] = [];
  let failNextRead = false;
  let complete = false;
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.includes("/media/")) { media.push(url.search); return route.fulfill({ contentType: "image/svg+xml", body: preview }); }
    if (path.endsWith("/admin/trash")) {
      if (failNextRead) {
        images[0].restore_task = { id: 1, status: "failed", stage: "处理失败", error: "原文件已失效" };
        failNextRead = false;
      }
      return route.fulfill({ json: { items: images, total: images.length, page: 1, page_size: 50 } });
    }
    if (path.endsWith("/images/actions")) {
      const body = route.request().postDataJSON(); restores.push(body);
      if (complete) images = images.filter(image => !body.ids.includes(image.id));
      else images[0].restore_task = { id: 1, status: "queued", stage: "等待处理", error: null };
      return route.fulfill({ json: { ok: true, tasks: [{ task_id: 1, image_id: 11 }] } });
    }
    if (path.endsWith("/tasks/1/cancel")) {
      images[0].restore_task = { id: 1, status: "cancelled", stage: "已取消", error: null };
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/directories")) return route.fulfill({ json: ["photos"] });
    if (path.endsWith("/people")) return route.fulfill({ json: [{ id: 7, name: "测试人物", accounts: [], groups: [] }] });
    return route.fulfill({ json: /\/(session|site)$/.test(path) ? { admin: true } : [] });
  });
  await page.goto("/admin/review?state=hidden");
  await expect(page.getByRole("heading", { name: "图片 #11", exact: true })).toBeVisible();
  const referenceHint = page.getByText("关联参考图已暂停使用，恢复成功后重新启用", { exact: true });
  await expect(referenceHint).toBeVisible();
  await page.getByRole("button", { name: "下一张", exact: true }).click();
  await expect(referenceHint).toHaveCount(0);
  await page.getByRole("button", { name: "上一张", exact: true }).click();
  await expect(referenceHint).toBeVisible();
  await expect(page.locator('[aria-label="审核状态"]')).toContainText("回收站");
  await expect(page.getByRole("button", { name: "全部确认", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新检测", exact: true })).toHaveCount(0);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/gallery-faces/trash-${width}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: "恢复当前图片", exact: true }).click();
  await expect(page.getByRole("button", { name: "恢复当前图片", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "取消恢复", exact: true }).click();
  await expect(page.getByText("恢复已取消，图片仍在回收站。")).toBeVisible();
  await page.getByRole("button", { name: "恢复当前图片", exact: true }).click();
  failNextRead = true;
  await expect(page.getByText(/恢复失败：原文件已失效/)).toBeVisible();
  await page.locator('[aria-label="恢复文件所在目录"]').click();
  await page.locator(".n-base-select-option").filter({ hasText: /^photos$/ }).click();
  complete = true;
  await page.getByRole("button", { name: "恢复当前图片", exact: true }).click();
  await expect(page.getByRole("heading", { name: "图片 #12", exact: true })).toBeVisible();
  expect(restores.at(-1)).toEqual({ action: "restore", ids: [11], directory: "photos" });
  expect(media.every(query => query === "?thumbnail=true")).toBe(true);
  await page.getByRole("button", { name: "全选本页", exact: true }).click();
  await page.getByRole("button", { name: "恢复所选 1 张", exact: true }).click();
  await expect(page.getByRole("heading", { name: "回收站为空", exact: true })).toBeVisible();
});

test("trash pages do not truncate older records and selections reset between pages", async ({ page }) => {
  const restored: number[][] = [];
  const images = Array.from({ length: 51 }, (_, index) => photo(index + 1));
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: preview });
    if (path.endsWith("/admin/trash")) {
      const current = Number(url.searchParams.get("page"));
      return route.fulfill({ json: { items: images.slice((current - 1) * 50, current * 50), page: current, total: 51, page_size: 50 } });
    }
    if (path.endsWith("/images/actions")) {
      restored.push(route.request().postDataJSON().ids);
      return route.fulfill({ json: { ok: true, tasks: [] } });
    }
    return route.fulfill({ json: /\/(session|site)$/.test(path) ? { admin: true } : [] });
  });
  await page.goto("/admin/review?state=trash");
  await page.getByRole("checkbox", { name: "选择回收站图片 1", exact: true }).check();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "图片 #51", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "恢复当前图片", exact: true }).click();
  await expect.poll(() => restored).toEqual([[51]]);
});
