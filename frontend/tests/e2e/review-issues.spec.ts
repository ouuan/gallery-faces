import { test, expect } from "@playwright/test";

test("review reasons follow the current photo and disappear in specific filters", async ({ page }) => {
  const source = { id: 1, platform: "x", author: "fixture", published_at: "2026-01-01", url: "https://x.com/fixture/status/1" };
  const face = { id: 1, box: [0, 0, 20, 20], person_id: null, locked: 0, ignored: 0, candidates: [], revision: 0 };
  const images = [
    { id: 1, detection: "done", faces: [face, { ...face, id: 2, person_id: 7 }, { ...face, id: 3, person_id: 7, locked: 1 }, { ...face, id: 4, person_id: 7, ignored: 1 }], sources: [] },
    { id: 2, detection: "done", faces: [], sources: [source] },
    { id: 3, detection: "failed", faces: [], sources: [source] },
    { id: 4, detection: "pending", faces: [], sources: [source] },
    { id: 5, detection: "done", faces: [{ ...face, locked: 1 }, { ...face, id: 2, ignored: 1 }], sources: [source, { ...source, author: null }] },
  ].map((image) => ({ width: 800, height: 600, ...image }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/") || path.endsWith("/crop"))
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith("/admin/images")) return route.fulfill({ json: images });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site") || path.endsWith("/settings")) return route.fulfill({ json: {} });
    if (path.endsWith("/people")) return route.fulfill({ json: [{ id: 7, name: "测试人物", groups: [], accounts: [] }] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review?state=image&image=1");
  const issues = page.locator(".review-main .n-alert").filter({ hasText: "待审核问题" });
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(issues).toContainText("来源待补全");
    await expect(issues).toContainText("未知人物（1 个人脸）");
    await expect(issues).toContainText("自动识别结果待确认（1 个人脸）");
    await issues.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/gallery-faces/review-issues-${width}.png` });
  }
  for (const [id, reason] of [[2, "未检测到人脸"], [3, "检测失败"], [4, "等待检测"]] as const) {
    await page.getByRole("button", { name: `审核图片（${id}，共 1 个版本）`, exact: true }).click();
    await expect(issues).toContainText(reason);
    await expect(issues).not.toContainText("未知人物");
    if (id !== 2) await expect(issues).not.toContainText("未检测到人脸");
  }
  await page.getByRole("button", { name: "审核图片（5，共 1 个版本）", exact: true }).click();
  await expect(issues).toHaveCount(0);
  await page.getByRole("button", { name: "审核图片（1，共 1 个版本）", exact: true }).click();
  for (const label of ["全部待审核", "全部在库图片", "未知人物", "同一人物出现多次", "无人脸", "检测失败", "来源待补全", "等待检测"]) {
    await page.locator('[aria-label="审核状态"]').click();
    await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${label}$`) }).click();
    if (label === "同一人物出现多次") await expect(page).toHaveURL(/state=repeated_person/);
    await expect(page.getByRole("button", { name: "审核图片（1，共 1 个版本）", exact: true })).toBeVisible();
    if (["全部待审核", "全部在库图片"].includes(label)) await expect(issues).toContainText("同一人物出现多次：测试人物（2 个人脸）");
    else await expect(issues).toHaveCount(0);
  }
});
