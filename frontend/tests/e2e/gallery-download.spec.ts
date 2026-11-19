import { test as base, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

// Chromium's native downloads bypass page.route. Serve a real attachment so
// these tests exercise the download manager rather than only a mocked request.
const test = base.extend<{ archiveUrl: string }>({
  archiveUrl: async ({}, use) => {
    const server = createServer((_, response) => {
      response.writeHead(200, {
        "Content-Type": "application/zip",
        "Content-Disposition": 'attachment; filename="gallery-test.zip"',
      });
      response.end(Buffer.from("504b0506000000000000000000000000000000000000", "hex"));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    try {
      await use(`http://127.0.0.1:${(server.address() as AddressInfo).port}/download.zip`);
    } finally {
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  },
});

const photos = Array.from({ length: 6 }, (_, index) => ({
  id: index + 1, image_id: index + 101,
  width: 600, height: [400, 800, 600][index % 3],
  thumbnail_url: `/fixtures/download-${index}.svg`,
  image_url: `/fixtures/download-${index}.svg`, download_url: "",
  people: [{ id: index + 1, name: `人物 ${index + 1}` }], source_count: 1,
  matched_source: { platform: "x", author: "fixture", published_at: "2026-01-01T00:00:00Z" },
}));

async function setup(page: Page, archiveUrl: string, options: { fail?: boolean; count?: number } = {}) {
  const selections: number[][] = [];
  await page.route("**/fixtures/download-*.svg", route => route.fulfill({
    contentType: "image/svg+xml",
    body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><rect width="600" height="600" fill="#68717d"/><text x="40" y="300" fill="white" font-size="40">布局示例</text></svg>',
  }));
  await page.route("**/api/v1/**", route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/gallery/downloads")) {
      selections.push(route.request().postDataJSON().group_ids);
      if (options.fail) return route.fulfill({ status: 404, json: { detail: "部分照片已不可用，请刷新后重新选择" } });
      return route.fulfill({ json: { download_url: archiveUrl + "?groups=" + selections.at(-1)!.join(",") } });
    }
    if (url.pathname.endsWith("/gallery")) return route.fulfill({ json: {
      items: options.count ? Array.from({ length: options.count }, (_, i) => ({ ...photos[i % 6], id: i + 1 })) :
        url.searchParams.has("cursor") ? photos.slice(4) : photos.slice(0, 4),
      next_cursor: options.count || url.searchParams.has("cursor") ? null : "next",
    } });
    return route.fulfill({ json: /\/(people|groups)$/.test(url.pathname) ? [] : {} });
  });
  await page.goto("/");
  await expect(page.locator(".photo-card")).toHaveCount(options.count || 4);
  return selections;
}

for (const width of [390, 1280]) {
  test(`select, append and download without opening details at ${width}px`, async ({ page, archiveUrl }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const selections = await setup(page, archiveUrl);
    await page.getByRole("button", { name: "多选下载" }).click();
    const download = page.getByRole("button", { name: "下载 ZIP", exact: true });
    await expect(download).toBeDisabled();
    const first = page.getByRole("button", { name: "选择 人物 1 的照片" });
    await first.focus();
    await page.keyboard.press("Space");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    await expect(page).not.toHaveURL(/photo=/);
    await expect(page.getByText("已选 1 组", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "加载更多" }).click();
    await expect(page.locator(".photo-card")).toHaveCount(6);
    await expect(first).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "全选已加载" }).click();
    await expect(page.getByText("已选 6 组", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "取消全选" }).click();
    await expect(download).toBeDisabled();
    await first.click();
    await page.getByRole("button", { name: "选择 人物 5 的照片" }).click();
    const downloaded = page.waitForEvent("download");
    await download.click();
    const file = await downloaded;
    expect(file.suggestedFilename()).toBe("gallery-test.zip");
    expect(await file.failure()).toBeNull();
    expect(selections).toEqual([[1, 5]]);
    await expect(page.getByText("已发起下载，可在浏览器中查看进度")).toBeVisible();
    await expect(page).toHaveURL(/\/$/);

    for (const layout of ["方格", "瀑布流", "等高排列"]) {
      await page.locator('[aria-label="布局"]').click();
      await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${layout}$`) }).click();
      await expect(first).toHaveAttribute("aria-pressed", "true");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    mkdirSync("../.impeccable/review", { recursive: true });
    for (const theme of ["浅色", "深色"]) {
      await page.locator('[aria-label="主题"]').click();
      await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${theme}$`) }).click();
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: `../.impeccable/review/download-${width}-${theme}.png`, fullPage: true });
    }
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await expect(page.getByRole("button", { name: "多选下载" })).toBeVisible();
    await expect(first).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test("download error keeps selection for retry; filter changes clear it", async ({ page, archiveUrl }) => {
  const options = { fail: true };
  const selections = await setup(page, archiveUrl, options);
  await page.getByRole("button", { name: "多选下载" }).click();
  await page.getByRole("button", { name: "选择 人物 1 的照片" }).click();
  await page.getByRole("button", { name: "下载 ZIP" }).click();
  await expect(page.getByText("部分照片已不可用，请刷新后重新选择")).toBeVisible();
  await expect(page.getByText("已选 1 组", { exact: true })).toBeVisible();
  options.fail = false;
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 ZIP" }).click();
  await downloaded;
  expect(selections).toEqual([[1], [1]]);
  await page.locator('[aria-label="排序"]').click();
  await page.locator(".n-base-select-option").filter({ hasText: /^最早发布$/ }).click();
  await expect(page.getByRole("button", { name: "多选下载" })).toBeVisible();
  await page.getByRole("button", { name: "多选下载" }).click();
  await expect(page.getByText("已选 0 组", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "多选下载" })).toBeVisible();
});

test("cancelling preparation prevents a late download", async ({ page, archiveUrl }) => {
  await setup(page, archiveUrl);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/v1/gallery/downloads", async route => {
    await pending;
    await route.fulfill({ json: { download_url: archiveUrl + "?groups=1" } }).catch(() => {});
  });
  const downloads: string[] = [];
  page.on("download", file => downloads.push(file.url()));
  await page.getByRole("button", { name: "多选下载" }).click();
  await page.getByRole("button", { name: "选择 人物 1 的照片" }).click();
  await page.getByRole("button", { name: "下载 ZIP" }).click();
  await expect(page.getByRole("button", { name: "下载 ZIP" })).toHaveClass(/n-button--loading/);
  await page.getByRole("button", { name: "取消", exact: true }).click();
  release();
  await page.getByRole("button", { name: "多选下载" }).click();
  await expect(page.getByText("已选 0 组", { exact: true })).toBeVisible();
  expect(downloads).toEqual([]);
});

test("large selections explain the per-download limit", async ({ page, archiveUrl }) => {
  await setup(page, archiveUrl, { count: 201 });
  await page.getByRole("button", { name: "多选下载" }).click();
  await page.getByRole("button", { name: "全选已加载" }).click();
  await expect(page.getByText("已选 201 组", { exact: true })).toBeVisible();
  await expect(page.getByText(/每次最多 200 组/)).toBeVisible();
  await expect(page.getByRole("button", { name: "下载 ZIP" })).toBeDisabled();
  await page.locator(".photo-card").first().click();
  await expect(page.getByRole("button", { name: "下载 ZIP" })).toBeEnabled();
});
