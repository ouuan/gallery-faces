import { test, expect, type Page, type Route } from "@playwright/test";

const photos = Array.from({ length: 16 }, (_, i) => ({
  id: i + 1, image_id: i + 1,
  width: 600, height: [900, 300, 600, 400][i % 4],
  thumbnail_url: `/fixtures/masonry-${i}.svg`,
  image_url: `/fixtures/masonry-${i}.svg`, download_url: "",
  people: [{ id: i + 1, name: i === 2 ? "很长的人物名称用于验证文字换行时照片仍然不会重叠" : `人物 ${i + 1}` }],
  source_count: i % 3 + 1,
  matched_source: { platform: "x", author: "fixture", published_at: "2026-01-01T00:00:00Z", url: "https://example.com" },
}));

async function boxes(page: Page) {
  return page.locator(".photo-card").evaluateAll((cards) => cards.map((card) => {
    const r = card.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  }));
}

async function checkLayout(page: Page, columns: number) {
  await expect(async () => {
    const cards = await boxes(page);
    expect(cards.length).toBeGreaterThan(columns);
    const grid = await page.locator(".photo-grid").boundingBox();
    expect(grid).not.toBeNull();
    const bottoms = Array<number>(columns).fill(grid!.y);
    const lefts = cards.slice(0, columns).map((card) => card.x);
    expect(new Set(lefts).size).toBe(columns);
    expect(lefts).toEqual([...lefts].sort((a, b) => a - b));
    for (const card of cards) {
      const shortest = bottoms.indexOf(Math.min(...bottoms));
      expect(Math.abs(card.x - lefts[shortest])).toBeLessThan(1);
      expect(Math.abs(card.y - bottoms[shortest])).toBeLessThan(1);
      expect(card.x + card.width).toBeLessThanOrEqual(grid!.x + grid!.width + 1);
      bottoms[shortest] = card.y + card.height;
    }
    expect(Math.abs(grid!.y + grid!.height - Math.max(...bottoms))).toBeLessThan(1);
    const more = await page.locator(".load-more").boundingBox();
    expect(more!.y).toBeGreaterThanOrEqual(Math.max(...bottoms) - 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }).toPass();
}

test("masonry preserves sorted reading order through append, resize, layout and filter changes", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("layout", "masonry"));
  let releaseImages!: () => void;
  const imagesReady = new Promise<void>((resolve) => { releaseImages = resolve; });
  await page.route("**/fixtures/masonry-*.svg", async (route) => {
    await imagesReady;
    const i = Number(route.request().url().match(/masonry-(\d+)/)![1]);
    const photo = photos[i];
    await route.fulfill({ contentType: "image/svg+xml", body: `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="${photo.height}"><rect width="100%" height="100%" fill="#8799aa"/><text x="24" y="60" font-size="32">布局示例 ${i + 1}</text></svg>` });
  });
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/gallery")) {
      const items = url.searchParams.has("cursor") ? photos.slice(10) :
        url.searchParams.get("sort") === "oldest" ? [...photos].reverse().slice(0, 8) : photos.slice(0, 10);
      return route.fulfill({ json: { items, next_cursor: items.length === 10 ? "next" : null } });
    }
    return route.fulfill({ json: /\/(people|groups)$/.test(url.pathname) ? [] : {} });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".photo-card")).toHaveCount(10);
  await checkLayout(page, 3);
  const beforeImages = await boxes(page);
  releaseImages();
  await expect(page.locator(".photo-card img").first()).toHaveJSProperty("complete", true);
  await checkLayout(page, 3);
  expect(await boxes(page)).toEqual(beforeImages);

  await page.getByRole("button", { name: "加载更多" }).scrollIntoViewIfNeeded();
  const beforeAppend = await boxes(page);
  await page.getByRole("button", { name: "加载更多" }).click();
  await expect(page.locator(".photo-card")).toHaveCount(16);
  await checkLayout(page, 3);
  expect((await boxes(page)).slice(0, 10)).toEqual(beforeAppend);

  for (const [width, columns] of [[390, 2], [1280, 3], [1440, 4]]) {
    await page.setViewportSize({ width, height: 900 });
    await checkLayout(page, columns);
    await page.locator(".photo-card").first().focus();
    await page.keyboard.press("Tab");
    await expect(page.locator(".photo-card").nth(1)).toBeFocused();
    await page.evaluate(() => window.scrollTo(0, 0));
    for (const theme of ["浅色", "深色"]) {
      await page.locator('[aria-label="主题"]').click();
      await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${theme}$`) }).click();
      await expect(page.locator(".n-base-select-option:visible")).toHaveCount(0);
      await checkLayout(page, columns);
      await page.screenshot({ path: `/tmp/gallery-faces/masonry-${width}-${theme}.png` });
    }
  }

  for (const layout of ["方格", "等高排列", "瀑布流"]) {
    await page.locator('[aria-label="布局"]').click();
    await page.locator(".n-base-select-option").filter({ hasText: new RegExp(`^${layout}$`) }).click();
    if (layout === "瀑布流") await checkLayout(page, 4);
    else {
      await expect(page.locator(".photo-card").first()).toHaveCSS("position", "static");
      expect(await page.locator(".photo-grid").evaluate((grid) => (grid as HTMLElement).style.height)).toBe("");
    }
  }
  await page.locator('[aria-label="排序"]').click();
  await page.locator(".n-base-select-option").filter({ hasText: /^最早发布$/ }).click();
  await expect(page.locator(".photo-card")).toHaveCount(8);
  await expect(page.locator(".photo-card").first()).toContainText("人物 16");
  await checkLayout(page, 4);
  expect(errors).toEqual([]);
});

for (const [width, columns] of [[390, 2], [1280, 3], [1440, 4]]) {
  test(`masonry preserves scroll position through consecutive pages at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => localStorage.setItem("layout", "masonry"));
    const items = Array.from({ length: 42 }, (_, i) => ({
      ...photos[i % photos.length], id: i + 1, image_id: i + 1,
    }));
    let pending: Route | undefined;
    await page.route("**/fixtures/masonry-*.svg", (route) => {
      const i = Number(route.request().url().match(/masonry-(\d+)/)![1]);
      return route.fulfill({ contentType: "image/svg+xml", body: `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="${photos[i].height}"/>` });
    });
    await page.route("**/api/v1/**", (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/gallery")) {
        if (url.searchParams.has("cursor")) { pending = route; return; }
        return route.fulfill({ json: { items: items.slice(0, 18), next_cursor: "18" } });
      }
      return route.fulfill({ json: /\/(people|groups)$/.test(url.pathname) ? [] : {} });
    });
    await page.goto("/");
    await expect(page.locator(".photo-card")).toHaveCount(18);
    await checkLayout(page, columns);

    for (const [start, end] of [[18, 36], [36, 42]]) {
      const more = page.getByRole("button", { name: "加载更多", exact: true });
      await more.scrollIntoViewIfNeeded();
      const beforeScroll = await page.evaluate(() => window.scrollY);
      expect(beforeScroll).toBeGreaterThan(500);
      const beforeCards = await boxes(page);
      const expectStable = async () => {
        expect(Math.abs(await page.evaluate(() => window.scrollY) - beforeScroll)).toBeLessThanOrEqual(1);
        const afterCards = (await boxes(page)).slice(0, start);
        for (let i = 0; i < start; i++) {
          for (const key of ["x", "y", "width", "height"] as const)
            expect(Math.abs(afterCards[i][key] - beforeCards[i][key])).toBeLessThanOrEqual(1);
        }
      };
      await more.click();
      await expect.poll(() => !!pending).toBe(true);
      expect(new URL(pending!.request().url()).searchParams.get("cursor")).toBe(String(start));
      await expect(page.locator(".load-more button")).toHaveClass(/n-button--loading/);
      await expectStable();
      await pending!.fulfill({ json: { items: items.slice(start, end), next_cursor: end < items.length ? String(end) : null } });
      pending = undefined;
      await expect(page.locator(".photo-card")).toHaveCount(end);
      await checkLayout(page, columns);
      // Include the subsequent ResizeObserver/animation-frame layout pass.
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await expectStable();
    }
    await expect(page.getByRole("button", { name: "加载更多", exact: true })).toHaveCount(0);
  });
}
