import { test, expect } from "@playwright/test";

test("source text only offers expansion when clipped", async ({ page }) => {
  const sources = ["简短正文", "第一行\n第二行\n第三行", "这是一段需要根据容器宽度折行的正文。".repeat(12)].map((post_text, i) => ({
    id: i + 1, platform: "x", author: "fixture", published_at: "2026-01-01",
    url: "https://example.com", post_text,
  }));
  const photo = { id: 7, image_id: 501, width: 800, height: 600, people: [],
    source_count: 3, sources, matched_source: sources[0],
    image_url: "", thumbnail_url: "", download_url: "" };
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/session")) return route.fulfill({ status: 401, json: {} });
    if (path.endsWith("/gallery")) return route.fulfill({ json: { items: [photo], next_cursor: null } });
    if (path.endsWith("/gallery/7")) return route.fulfill({ json: photo });
    return route.fulfill({ json: path.endsWith("/site") ? {} : [] });
  });
  await page.goto("/?photo=7");
  const blocks = page.locator(".source-block");
  await expect(blocks).toHaveCount(3);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(blocks.nth(0).getByRole("button")).toHaveCount(0);
    await expect(blocks.nth(1).getByRole("button")).toHaveCount(0);
    const long = blocks.nth(2);
    await long.getByRole("button", { name: "展开正文" }).click();
    await expect(long.locator("p")).not.toHaveClass(/clamped/);
    await long.getByRole("button", { name: "收起正文" }).click();
    await expect(long.locator("p")).toHaveClass(/clamped/);
    await page.locator(".detail-sidebar").screenshot({ path: `/tmp/gallery-faces/source-text-${width}.png` });
  }
  // Width changes can reveal all text without changing the capped paragraph height.
  await blocks.nth(2).evaluate((el) => { el.style.width = "2000px"; });
  await expect(blocks.nth(2).getByRole("button")).toHaveCount(0);
  await blocks.nth(2).evaluate((el) => { el.style.width = ""; });
  await expect(blocks.nth(2).getByRole("button", { name: "展开正文" })).toBeVisible();
});
