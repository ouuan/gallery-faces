import { test, expect } from "@playwright/test";
for (const zone of ["Asia/Shanghai", "America/New_York", "Asia/Kathmandu"]) {
  test.describe(zone, () => {
    test.use({ timezoneId: zone });
    test("local pickers preserve instants through URL refresh and history", async ({ page }) => {
      await page.route("**/api/v1/**", route => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith("/gallery")) return route.fulfill({ json: { items: [], next_cursor: null } });
        if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
        if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
        if (path.endsWith("/tasks")) return route.fulfill({ json: { items: [], total: 0, page: 1 } });
        return route.fulfill({ json: [] });
      });
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto("/?start=2026-03-08T05%3A00%3A00Z&end=2026-03-09T04%3A00%3A00Z");
      const filters = page.locator(".desktop-filters");
      await expect(filters).toContainText(zone === "Asia/Kathmandu" ? "Asia/Katmandu" : zone);
      if (zone === "America/New_York") {
        await expect(filters).toContainText("开始 UTC-5 / 结束 UTC-4");
        await expect(filters.getByLabel("开始时间", { exact: true })).toHaveValue("2026-03-08 00:00:00");
      }
      if (zone === "Asia/Kathmandu") await expect(filters).toContainText("UTC+5:45");
      const before = await filters.getByLabel("开始时间", { exact: true }).inputValue();
      await page.reload();
      await expect(filters.getByLabel("开始时间", { exact: true })).toHaveValue(before);
      const input = filters.getByLabel("开始时间", { exact: true });
      await input.fill("2026-03-07 12:34:56");
      await input.press("Enter");
      await page.getByRole("heading", { name: "筛选" }).click().catch(() => page.locator("h1").click());
      await expect.poll(() => new URL(page.url()).searchParams.get("start")).not.toBe("2026-03-08T05:00:00Z");
      await page.goBack();
      await expect(input).toHaveValue(before);
      await page.goto("/?start=2026-01-01");
      await expect(filters).toContainText("重新选择");
      await page.goto("/admin/import");
      await expect(page.locator(".import-form")).toContainText(zone === "Asia/Kathmandu" ? "Asia/Katmandu" : zone);
      await page.locator(".import-form .n-date-picker input").first().click();
      await expect(page.locator(".n-date-panel")).toBeVisible();
      await page.waitForTimeout(350);
      await page.screenshot({ path: "/tmp/gallery-faces/datetime-" + zone.replaceAll("/", "-") + ".png" });
      await page.keyboard.press("Escape");
    });
  });
}
