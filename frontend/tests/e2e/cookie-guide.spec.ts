import { expect, test } from "@playwright/test";

for (const width of [390, 1280]) {
  test(`Cookie guide scrolls without moving its close action at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 720 });
    await page.route("**/api/v1/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/media-cache")) return route.fulfill({ status: 503 });
      return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? { cookies: {} } : [] });
    });
    await page.goto("/admin/settings");
    const trigger = page.getByRole("button", { name: "Cookie 导出指南" });
    await trigger.click();
    const guide = page.getByRole("dialog", { name: "Cookie 导出指南" });
    const close = guide.getByRole("button", { name: "关闭指南" });
    const heading = guide.getByRole("heading", { name: "Cookie 导出指南", exact: true });
    await expect(heading).toBeInViewport();
    await expect(close).toBeInViewport();
    const privacy = guide.getByText(/Cookie 包含登录凭据/);
    await expect(privacy).not.toBeInViewport();
    await privacy.scrollIntoViewIfNeeded();
    await expect(privacy).toBeInViewport();
    await expect(heading).toBeInViewport();
    await expect(close).toBeInViewport();
    await close.click();
    await expect(trigger).toBeFocused();
    await trigger.press("Enter");
    await page.keyboard.press("Escape");
    await expect(guide).toBeHidden();
  });
}
