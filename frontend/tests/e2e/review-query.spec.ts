import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.includes("/media/"))
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (path.endsWith("/admin/images")) {
      const ids = url.searchParams.has("image_id") ? [Number(url.searchParams.get("image_id"))]
        : url.searchParams.get("state") === "failed" ? [] : [11, 22, 33];
      return route.fulfill({ json: ids.map((id) => ({ id, width: 800, height: 600, detection: "done", faces: [], sources: [] })) });
    }
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site") || path.endsWith("/settings")) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
});

test("restores category and image and updates navigation without refetching", async ({ page }) => {
  let requests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/admin/images")) requests++;
  });
  await page.goto("/admin/review?state=unknown&image=22&extra=keep");
  await expect(page.locator('[aria-label="审核状态"]')).toContainText("未知人物");
  await expect(page.getByRole("heading", { name: "图片 #22", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一张", exact: true }).click();
  await expect(page).toHaveURL(/state=unknown&image=33&extra=keep/);
  await page.getByRole("button", { name: "上一张", exact: true }).click();
  await expect(page).toHaveURL(/image=22/);
  await page.getByRole("button", { name: "审核图片 11", exact: true }).click();
  await expect(page).toHaveURL(/image=11/);
  expect(requests).toBe(1);
  await page.reload();
  await expect(page.getByRole("heading", { name: "图片 #11", exact: true })).toBeVisible();
  await expect(page.locator('[aria-label="审核状态"]')).toContainText("未知人物");
});

test("opens explicit single-image links and records category changes and empty lists", async ({ page }) => {
  await page.goto("/admin/review?state=image&image=22");
  await expect(page.locator('[aria-label="审核状态"]')).toContainText("当前图片");
  await expect(page).toHaveURL(/state=image/);
  await expect(page.getByRole("button", { name: /^审核图片 / })).toHaveCount(1);
  for (const [label, state] of [["全部图片", "all"], ["检测失败", "failed"]]) {
    await page.locator('[aria-label="审核状态"]').click();
    await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${label}$`) }).click();
    await expect(page).toHaveURL(new RegExp(`state=${state}`));
    if (state === "all") await expect(page).toHaveURL(/image=11/);
    else {
      await expect(page.getByText("没有需要处理的照片")).toBeVisible();
      expect(new URL(page.url()).searchParams.has("image")).toBe(false);
    }
  }
});

test("falls back for invalid categories and missing images", async ({ page }) => {
  for (const query of ["state=unknown&image=999", "state=invalid&image=bad", "state=all&image=-1", "image=999"]) {
    await page.goto(`/admin/review?${query}`);
    await expect(page.getByRole("heading", { name: "图片 #11", exact: true })).toBeVisible();
    await expect(page).toHaveURL(/image=11/);
    expect(new URL(page.url()).searchParams.get("state")).toBe(query.includes("unknown") ? "unknown" : query.includes("state=all") ? "all" : "review");
  }
});
