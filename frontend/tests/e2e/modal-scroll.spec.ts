import { test, expect, type Page } from "@playwright/test";

async function expectLocked(page: Page) {
  await expect(page.locator("html")).toHaveCSS("overflow-y", "hidden");
  const before = await page.evaluate(() => scrollY);
  await page.mouse.move(5, 700);
  await page.mouse.wheel(0, 300);
  // Allow the browser to process the wheel event before checking the background.
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => scrollY)).toBe(before);
}

async function expectScrollable(page: Page, marginRight: string) {
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("html")).not.toHaveCSS("overflow-y", "hidden");
  expect(await page.locator("html").evaluate(el => el.style.marginRight)).toBe(marginRight);
  const before = await page.evaluate(() => scrollY);
  await page.mouse.move(5, 700);
  await page.mouse.wheel(0, before > 100 ? -300 : 300);
  await expect.poll(() => page.evaluate(() => scrollY)).not.toBe(before);
}

for (const [kind, width] of [["source", 390], ["group", 1280], ["person", 390]] as const) {
  test(`${kind} modal releases scrolling after every close at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 720 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let failSave = true;
    let writes = 0;
    const source = { id: 1, platform: "x", author: "fixture", author_name: "", published_at: null, url: "https://x.com/fixture/status/1", post_text: "" };
    await page.route("**/api/v1/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== "GET") {
        writes++;
        return route.fulfill(failSave
          ? { status: 500, json: { detail: "测试保存失败" } }
          : { json: { id: 7 } });
      }
      if (path.includes("/media/") || path.endsWith("/crop"))
        return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
      if (path.endsWith("/images")) return route.fulfill({ json: [{
        id: 1, width: 800, height: 600, detection: "done",
        sources: Array.from({ length: 20 }, (_, i) => ({ ...source, id: i + 1 })),
        faces: [{ id: 1, revision: 0, box: [20, 20, 40, 40], person_id: null, has_embedding: true, locked: false, ignored: false, candidates: [] }],
      }] });
      if (path.endsWith("/groups")) return route.fulfill({ json: Array.from({ length: 30 }, (_, i) => ({ id: i + 1, name: `分组${i + 1}` })) });
      if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
      return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
    });
    await page.goto(kind === "group" ? "/admin/people" : "/admin/review?state=all");
    if (kind === "group") await page.getByRole("button", { name: "分组", exact: true }).click();
    const open = async () => {
      if (kind === "person") {
        const more = page.getByRole("button", { name: "新增", exact: true }).first();
        await more.focus();
        await page.keyboard.press("Enter");
        await page.getByRole("menuitem", { name: "人物", exact: true }).click();
      } else {
        await page.getByRole("button", { name: kind === "source" ? "补全 / 编辑" : "编辑成员", exact: true }).first().click();
      }
      await expect(page.getByRole("dialog")).toBeVisible();
      await expectLocked(page);
    };
    const marginRight = await page.locator("html").evaluate(el => el.style.marginRight);
    // Reopening in one document catches leaked locks and stale modal state.
    for (const close of ["cancel", "escape", "mask"]) {
      await open();
      if (close === "cancel") await page.getByRole("dialog").getByRole("button", { name: "取消", exact: true }).click();
      else if (close === "escape") await page.keyboard.press("Escape");
      else await page.mouse.click(5, 700);
      await expectScrollable(page, marginRight);
    }
    if (kind === "person") {
      await open();
      await page.getByPlaceholder("输入新人物姓名").fill("草稿人物");
      const editor = page.getByRole("dialog", { name: "从人脸添加人物" });
      const confirmation = page.getByRole("dialog").filter({ hasText: "确认操作" });
      await editor.getByRole("button", { name: "取消", exact: true }).click();
      await confirmation.getByRole("button", { name: "取消", exact: true }).click();
      await expect(confirmation).toBeHidden();
      await expect(editor).toBeVisible();
      await expectLocked(page);
      await editor.getByRole("button", { name: "取消", exact: true }).click();
      await confirmation.getByRole("button", { name: "确认", exact: true }).click();
      await expectScrollable(page, marginRight);
    }
    await open();
    if (kind === "person") await page.getByPlaceholder("输入新人物姓名").fill("新人物");
    const save = page.getByRole("button", { name: kind === "source" ? "保存来源" : kind === "group" ? "保存分组" : "创建并确认人脸", exact: true });
    await save.click();
    await expect(page.getByText("测试保存失败", { exact: true })).toBeVisible();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expectLocked(page);
    failSave = false;
    await save.click();
    await expectScrollable(page, marginRight);
    expect(writes).toBe(2);
    expect(errors).toEqual([]);
  });
}
