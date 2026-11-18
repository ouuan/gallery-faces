import { test, expect } from "@playwright/test";

test("photo management link requires a session and opens the displayed image", async ({ page }) => {
  let admin = false;
  const source = { id: 1, post_id: 1, platform: "x", author: "fixture", published_at: "2026-01-01", url: "https://x.com/fixture/status/1" };
  // The public group ID differs from the image ID.
  const photo = { id: 7, image_id: 501, width: 800, height: 600, people: [], source_count: 1, matched_source: source, sources: [source] };
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
  admin = true;
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    const link = page.getByRole("link", { name: "管理此图片" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/admin/review?state=image&image=501");
    await page.screenshot({ path: `/tmp/gallery-faces/admin-link-${width}.png` });
  }
  await page.getByRole("link", { name: "管理此图片" }).click();
  await expect(page).toHaveURL(/\/admin\/review\?state=image&image=501$/);
  await expect(page.getByRole("button", { name: "审核图片 501", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "审核图片 501", exact: true })).toBeVisible();
});
