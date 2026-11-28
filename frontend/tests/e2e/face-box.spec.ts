import { test, expect, type Page } from "@playwright/test";

async function setup(page: Page) {
  const saved: { image: number; box: number[]; person_id: number | null }[] =
    [];
  let fail = true;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/admin/media/"))
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="600"><rect width="1200" height="600" fill="#8799aa"/></svg>',
      });
    if (/\/images\/\d+\/faces$/.test(path)) {
      if (fail) {
        fail = false;
        return route.fulfill({
          status: 409,
          json: { detail: "保存失败，请重试" },
        });
      }
      saved.push({
        image: Number(path.split("/").at(-2)),
        ...route.request().postDataJSON(),
      });
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/images"))
      return route.fulfill({
        json: [1, 2].map((id) => ({
          id,
          width: 1200,
          height: 600,
          faces: [],
          sources: [],
        })),
      });
    if (path.endsWith("/people"))
      return route.fulfill({
        json: [{ id: 7, name: "测试人物", groups: [], accounts: [] }],
      });
    if (path.endsWith("/site"))
      return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    if (path.endsWith("/session")) return route.fulfill({ json: { ok: true } });
    if (path.endsWith("/settings"))
      return route.fulfill({ json: { cookies: {} } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review");
  await expect(page.locator(".face-box-editor img")).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".face-box-editor img")
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(1200);
  return saved;
}
async function drag(page: Page, start: number[], end: number[]) {
  const editor = page.locator(".face-box-editor");
  await editor.scrollIntoViewIfNeeded();
  const bounds = (await editor.boundingBox())!;
  await page.mouse.move(
    bounds.x + start[0]! * bounds.width,
    bounds.y + start[1]! * bounds.height,
  );
  await page.mouse.down();
  await page.mouse.move(
    bounds.x + end[0]! * bounds.width,
    bounds.y + end[1]! * bounds.height,
    { steps: 5 },
  );
  await page.mouse.up();
}

test("drag boxes scale to original pixels, retry, clamp, cancel and reset on image change", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const saved = await setup(page);
  const save = page.getByRole("button", { name: "补框与标签", exact: true });
  await expect(page.getByPlaceholder("补框：左,上,宽,高（像素）")).toHaveCount(
    0,
  );
  await expect(save).toBeDisabled();
  await drag(page, [0.5, 0.6], [0.25, 0.2]);
  await expect(page.locator(".draft-box")).toBeVisible();
  await page.screenshot({
    path: "/tmp/gallery-faces/drag-box-desktop.png",
    animations: "disabled",
    fullPage: true,
  });
  await page.locator('.review-box-controls .n-cascader .n-base-selection').click();
  await page.locator('.review-box-controls .n-cascader input').fill("测试");
  await page
    .locator(".n-base-select-option")
    .filter({ hasText: "测试人物" })
    .click();
  await save.click();
  await expect(
    page.getByText("保存失败，请重试", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".draft-box")).toBeVisible();
  await save.click();
  await expect(page.locator(".draft-box")).toHaveCount(0);
  expect(saved).toEqual([
    { image: 1, box: [300, 120, 300, 240], person_id: 7 },
  ]);
  await drag(page, [0.8, 0.8], [1.1, 1.1]);
  await save.click();
  expect(saved[1]).toEqual({
    image: 1,
    box: [960, 480, 240, 120],
    person_id: 7,
  });
  await drag(page, [0.2, 0.2], [0.2, 0.2]);
  await expect(save).toBeDisabled();
  await drag(page, [0.2, 0.2], [0.4, 0.4]);
  await page.keyboard.press("Escape");
  await expect(page.locator(".draft-box")).toHaveCount(0);
  await drag(page, [0.2, 0.2], [0.4, 0.4]);
  await page.getByRole("button", { name: "取消补框", exact: true }).click();
  await expect(page.locator(".draft-box")).toHaveCount(0);
  await drag(page, [0.2, 0.2], [0.4, 0.4]);
  await page.getByRole("button", { name: "下一张", exact: true }).click();
  await expect(page.locator(".draft-box")).toHaveCount(0);
  await expect(save).toBeDisabled();
});

test("mobile touch drawing and pointer cancellation", async ({ browser, baseURL }) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    baseURL,
  });
  const page = await context.newPage();
  try {
    await setup(page);
    const editor = page.locator(".face-box-editor");
    await editor.scrollIntoViewIfNeeded();
    const bounds = (await editor.boundingBox())!;
    const cdp = await context.newCDPSession(page);
    const touch = (type: string, x?: number, y?: number) =>
      cdp.send("Input.dispatchTouchEvent", {
        type,
        touchPoints: x === undefined ? [] : [{ x, y }],
      });
    await touch(
      "touchStart",
      bounds.x + bounds.width * 0.2,
      bounds.y + bounds.height * 0.2,
    );
    await touch(
      "touchMove",
      bounds.x + bounds.width * 0.6,
      bounds.y + bounds.height * 0.7,
    );
    await touch("touchEnd");
    await expect(page.locator(".draft-box")).toBeVisible();
    const first = await page.locator(".draft-box").getAttribute("style");
    await touch(
      "touchStart",
      bounds.x + bounds.width * 0.1,
      bounds.y + bounds.height * 0.1,
    );
    await touch(
      "touchMove",
      bounds.x + bounds.width * 0.8,
      bounds.y + bounds.height * 0.8,
    );
    await touch("touchCancel");
    await expect(page.locator(".draft-box")).toHaveAttribute("style", first!);
    await expect(
      page.getByRole("button", { name: "补框与标签", exact: true }),
    ).toBeEnabled();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: "/tmp/gallery-faces/drag-box-mobile.png",
      animations: "disabled",
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
