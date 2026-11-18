import { test, expect } from "@playwright/test";

test("review more menu adds references for the selected person", async ({ page }) => {
  const requests: { path: string; body: unknown }[] = [];
  let fail = true;
  const face = { id: 1, revision: 0, box: [20, 20, 40, 40], person_id: null, has_embedding: true, locked: false, ignored: false, candidates: [{ person_id: 7, score: 0.9 }, { person_id: 8, score: 0.8 }] };
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/") || path.endsWith("/crop")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith("/references")) {
      requests.push({ path, body: route.request().postDataJSON() });
      return route.fulfill(fail ? { status: 503, json: { detail: "参考图保存失败" } } : { json: { ok: true } });
    }
    if (path.endsWith("/admin/images")) return route.fulfill({ json: [{ id: 1, width: 800, height: 600, detection: "done", sources: [], faces: [face, { ...face, id: 2, person_id: 7, has_embedding: false }] }] });
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/people")) return route.fulfill({ json: [7, 8].map(id => ({ id, name: `人物${id}`, groups: [], accounts: [] })) });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (/\/(settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/admin/review?state=all");
  const row = page.locator(".face-review").first();
  const more = row.getByRole("button", { name: "新增", exact: true });
  const reference = page.getByRole("menuitem", { name: "参考图", exact: true });
  await more.hover();
  await expect(reference).toHaveAttribute("aria-disabled", "true");
  await page.getByRole("menuitem", { name: "人物", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("从人脸添加人物");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await row.getByText("人物8", { exact: false }).click();
  await more.hover();
  await expect(reference).not.toHaveAttribute("aria-disabled", "true");
  await reference.click();
  await expect(page.getByText("参考图保存失败", { exact: true })).toBeVisible();
  fail = false;
  await more.hover();
  await reference.click();
  await expect(page.getByText("参考图已添加", { exact: true })).toBeVisible();
  expect(requests).toEqual(Array(2).fill({ path: "/api/v1/admin/people/8/references", body: { face_id: 1 } }));
  await page.locator(".face-review").nth(1).getByRole("button", { name: "新增", exact: true }).hover();
  await expect(reference).toHaveAttribute("aria-disabled", "true");
  await page.mouse.move(0, 0);
  await expect(reference).toBeHidden();
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(reference).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(reference).toBeHidden();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await more.hover();
    await expect(reference).toBeVisible();
    await page.screenshot({ path: `/tmp/gallery-faces/review-more-${width}.png` });
    await page.mouse.move(0, 0);
  }
});
