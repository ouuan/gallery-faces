import { test, expect } from "@playwright/test";

test.use({ reducedMotion: "reduce" });

test("each face selects and saves its own person independently", async ({ page }) => {
  page.on("pageerror", (error) => { throw error; });
  const saved: { face: number; person_id: number | null; locked: boolean; ignored: boolean }[] = [];
  const faces = [42, 17].map((id, index) => ({
    id, box: [(index + 1) * 30, 20, 20, 20], person_id: (index === 1 ? 8 : null) as number | null,
    locked: 0, ignored: 0, revision: 0, candidates: [8, 9, 10, 11, 12].map((person_id, i) => ({ person_id, score: 0.9 - i * 0.1 })),
  }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/") || path.endsWith("/crop"))
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (/\/admin\/faces\/\d+$/.test(path)) {
      const id = Number(path.split("/").pop());
      const body = route.request().postDataJSON();
      saved.push({ face: id, person_id: body.person_id, locked: body.locked, ignored: body.ignored });
      Object.assign(faces.find((face) => face.id === id)!, body);
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/admin/images"))
      return route.fulfill({ json: [1, 2].map((id) => ({ id, width: 800, height: 600, detection: "done", faces: id === 1 ? faces : [], sources: [] })) });
    if (path.endsWith("/feedback"))
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/people"))
      return route.fulfill({ json: [{ id: 7, name: "人物甲", groups: [], accounts: [] }, { id: 8, name: "人物乙", groups: [], accounts: [] }, ...[9, 10, 11, 12].map(id => ({ id, name: `候选人物较长的姓名${id}`, groups: [], accounts: [] }))] });
    if (path.endsWith("/references"))
      return route.fulfill({ json: [{ id: Number(path.split("/").at(-2)) }] });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site") || path.endsWith("/settings")) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review?state=image&image=1");
  const first = page.locator(".face-review").nth(0);
  const second = page.locator(".face-review").nth(1);
  await expect(first).toBeVisible();
  await expect(first.getByRole("heading")).toHaveText("人脸 #1");
  await expect(second.getByRole('heading')).toHaveText('人脸 #2');
  await expect(page.locator('.face-box-editor .face-box')).toHaveText(['#1', '#2']);
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  await expect(second.getByRole("button", { name: "确认", exact: true })).toBeEnabled();
  await expect(page.locator('.review-main > .field-label')).toHaveCount(0);
  await expect(first.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  await expect(second.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  await first.locator("label").filter({ has: page.getByRole("radio", { name: /人物乙/ }) }).click();
  await expect(first.getByRole("radio", { name: /人物乙/ })).toBeChecked();
  await first.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(first.locator(".n-cascader")).toContainText("未知人物");
  await expect(first.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  await expect(first.locator("input:checked")).toHaveCount(0);
  expect(saved).toEqual([]);
  await first.locator(".n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option__label").filter({ hasText: /^未分组$/ }).click();
  await page.locator(".people-cascader-menu .n-cascader-option__label").filter({ hasText: /^人物甲$/ }).click();
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeEnabled();
  await expect(second.locator(".n-cascader")).toContainText("人物乙");
  await second.locator("label").filter({ has: page.getByRole("radio", { name: /人物乙/ }) }).click();
  await expect(page.getByAltText("候选人物参考图")).toHaveCount(0);
  await expect(first.locator("input:checked")).toHaveCount(0);
  await expect(page.locator(".people-cascader-menu")).toHaveCount(0);
  for (const width of [390, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const candidates = first.getByRole("radiogroup");
      expect(await candidates.evaluate(el => el.scrollWidth > el.clientWidth)).toBeTruthy();
      expect(await candidates.locator("label").evaluateAll(els => new Set(els.map(el => el.getBoundingClientRect().top)).size)).toBe(1);
      await expect.poll(
        () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        { message: `Page should not overflow horizontally at ${width}px in ${theme} theme` },
      ).toBeLessThanOrEqual(0);
      await first.screenshot({ path: `/tmp/gallery-faces/face-person-${width}-${theme}.png` });
    }
  }
  const secondCandidates = second.getByRole("radiogroup");
  await second.getByRole("radio", { name: /人物乙/ }).focus();
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  await expect(second.getByRole("radio", { name: /姓名12/ })).toBeChecked();
  expect(await secondCandidates.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
  await second.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(second.getByRole("radio", { name: /人物乙/ })).toBeChecked();
  await first.getByRole("button", { name: "确认", exact: true }).click();
  await expect(first.locator(".n-cascader")).toContainText("人物甲");
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  await expect(second.getByRole("button", { name: "确认", exact: true })).toBeEnabled();
  await second.getByRole("button", { name: "确认", exact: true }).click();
  await expect(second.locator(".n-cascader")).toContainText("人物乙");
  await expect(second.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  expect(saved).toEqual([
    { face: 42, person_id: 7, locked: true, ignored: false },
    { face: 17, person_id: 8, locked: true, ignored: false },
  ]);
  await first.locator("label").filter({ has: page.getByRole("radio", { name: /人物乙/ }) }).click();
  await first.getByRole("button", { name: "撤销", exact: true }).click();
  await expect(first.locator(".n-cascader")).toContainText("人物甲");
  await expect(second.locator(".n-cascader")).toContainText("人物乙");
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  await expect(first.getByRole("button", { name: "撤销", exact: true })).toBeDisabled();
  expect(saved).toHaveLength(2);
  await first.locator("label").filter({ has: page.getByRole("radio", { name: /人物乙/ }) }).click();
  await page.getByRole("button", { name: "下一张", exact: true }).click();
  await page.getByRole("button", { name: "审核图片（1，共 1 个版本）", exact: true }).click();
  await expect(first.locator(".n-cascader")).toContainText("人物甲");
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  await expect(first.locator(".reference-grid")).toHaveCount(0);
  await first.locator(".n-base-selection").hover();
  await first.locator(".n-base-clear__clear").click();
  await expect(first.locator(".n-cascader")).toContainText("未知人物");
  await first.getByRole("button", { name: "确认", exact: true }).click();
  await expect.poll(() => saved.length).toBe(3);
  expect(saved[2]).toEqual({ face: 42, person_id: null, locked: false, ignored: false });
  await expect(first.getByRole("button", { name: "确认", exact: true })).toBeDisabled();
  await page.reload();
  await expect(first.locator(".n-cascader")).toContainText("未知人物");
  await expect(second.locator(".n-cascader")).toContainText("人物乙");
  await first.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.locator(".face-review")).toHaveCount(1);
  await expect(page.locator(".face-box-editor .face-box")).toHaveCount(1);
  await expect(first.getByRole('heading')).toHaveText('人脸 #1');
  await expect(page.locator('.face-box-editor .face-box')).toHaveText('#1');
  expect(saved[3]).toEqual({ face: 42, person_id: null, locked: true, ignored: true });
  await expect(page.getByRole("button", { name: /^(保存并下一张|暂不标记|恢复未知|撤销修改|误检)$/ })).toHaveCount(0);
});
