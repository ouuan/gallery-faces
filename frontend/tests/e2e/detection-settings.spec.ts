import { test, expect } from "@playwright/test";

test("detection threshold can be saved and restored", async ({ page }) => {
  let settings = {
    site_title: "Gallery Faces", detection_threshold: "0.5",
    threshold: "0.5", margin: "0.1", phash_distance: "4",
    aspect_tolerance: "0.01", ssim_threshold: "0.98",
    timezone: "Asia/Shanghai", cookies: {}, models_ready: true,
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: settings.site_title } });
    if (path.endsWith("/admin/settings")) {
      if (route.request().method() === "PUT") {
        settings = route.request().postDataJSON();
        return route.fulfill({ json: { ok: true } });
      }
      return route.fulfill({ json: settings });
    }
    if (path.endsWith("/admin/tasks")) return route.fulfill({ json: { items: [], total: 0, page: 1 } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/settings");
  const input = page.getByRole("textbox", { name: "人脸检测阈值" });
  await expect(input).toHaveValue("0.5");
  await input.fill("");
  await input.blur();
  await expect(page.getByRole("button", { name: "保存设置" })).toBeDisabled();
  await input.fill("0.3");
  await input.blur();
  await page.getByRole("button", { name: "保存设置" }).click();
  await expect.poll(() => Number(settings.detection_threshold)).toBe(0.3);
  await page.reload();
  await expect(input).toHaveValue("0.3");
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate((theme) => localStorage.setItem("theme", theme), theme);
      await page.reload();
      await expect(input).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: `/tmp/gallery-faces/detection-settings-${width}-${theme}.png`, fullPage: true });
    }
  }
});
