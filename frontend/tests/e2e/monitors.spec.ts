import { test, expect } from "@playwright/test";
test("monitor selection, partial batch results, resume and responsive themes", async ({ page }) => {
  const calls: any[] = [];
  const items = [1, 2].map(id => ({ id, platform: "x", username: id === 1 ? "alice" : "bob", interval_minutes: 60, paused: id === 2 ? 1 : 0, active_task_id: null, last_checked_at: null, next_check_at: "2026-11-19T00:00:00Z", last_result: "{}", last_status: null, last_error: null }));
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON(); calls.push({ path, body });
      if (path.endsWith("/batch")) return route.fulfill({ json: body.ids.map((id: number) => ({ id, status: id === 1 ? "error" : "queued", task_id: id === 2 ? 42 : null, error: id === 1 ? "已有活动任务，本项未提交；任务结束后重试" : undefined })) });
      return route.fulfill({ json: { id: 3, task_id: 43 } });
    }
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/monitors")) return route.fulfill({ json: items });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
    if (path.endsWith("/publisher-candidates")) return route.fulfill({ json: [{ platform: "x", username: "alice", label: "人物甲" }] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/monitors");
  await page.getByRole("checkbox", { name: "全选当前列表" }).check();
  await expect(page.locator(".monitor-manager")).toContainText("已选 2 项");
  await page.getByRole("button", { name: "补齐", exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("补齐 2 位发布者");
  const date = dialog.locator("input").first();
  await date.click();
  await page.waitForTimeout(350);
  await page.screenshot({ path: "/tmp/gallery-faces/backfill-picker-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  await page.screenshot({ path: "/tmp/gallery-faces/backfill-picker-mobile.png" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await date.fill("2020-01-01 12:34:56"); await date.press("Enter");
  await dialog.getByRole("button", { name: "确认补齐" }).click();
  await expect(page.locator(".monitor-manager")).toContainText("任务 #42");
  expect(calls[0].body.ids).toEqual([1, 2]);
  expect(calls[0].body.start).toMatch(/T.*Z$/);
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await expect(dialog).toContainText("补齐暂停期间");
  await dialog.getByRole("button", { name: "确认恢复" }).click();
  expect(calls.at(-1).body.mode).toBe("catch_up");
  await expect(dialog).not.toBeVisible();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(400);
      await page.screenshot({ path: `/tmp/gallery-faces/monitors-${width}-${theme}.png`, fullPage: true });
    }
  }
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await dialog.getByLabel("恢复方式").click();
  await page.getByText("指定起始时间", { exact: true }).click();
  await expect(dialog).toContainText("新的采集起点");
  await page.waitForTimeout(350);
  await page.screenshot({ path: "/tmp/gallery-faces/resume-mobile.png" });
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "删除", exact: true }).first().click();
  await expect(dialog).toContainText("删除 2 项监控");
  await expect(dialog).toContainText("已导入照片会保留");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});


test("create monitors from publisher groups and independent manual accounts with partial retry", async ({ page }) => {
  const calls: any[] = [];
  let fail = true;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/monitors") && route.request().method() === "POST") {
      const body = route.request().postDataJSON(); calls.push(body);
      return route.fulfill(body.username === "bob" && fail ? { status: 503, json: { detail: "稍后重试" } } : { json: { id: calls.length, task_id: calls.length } });
    }
    if (path.endsWith("/people")) return route.fulfill({ json: [
      { id: 1, name: "人物甲", groups: [], accounts: [{ platform: "x", username: "Alice" }, { platform: "instagram", username: "alice" }] },
      { id: 2, name: "人物乙", groups: [], accounts: [{ platform: "x", username: "alice" }] },
    ] });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/monitors");
  const form = page.locator(".monitor-create");
  await form.locator(".publisher-cascader .n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option").filter({ has: page.locator(".n-cascader-option__label", { hasText: /^未分组$/ }) }).locator(".n-checkbox").click();
  await form.getByRole("heading", { name: "添加发布者" }).click();
  await expect(form.getByLabel("账号 1 用户名")).toHaveValue("");
  await form.getByLabel("账号 1 用户名").fill("@ALICE");
  await form.getByRole("button", { name: "添加账号", exact: true }).click();
  await form.getByLabel("账号 2 用户名").fill("bob");
  await form.getByRole("checkbox").check();
  await form.getByLabel("起始时间", { exact: true }).fill("2020-01-01 12:34:56");
  await form.getByLabel("起始时间", { exact: true }).press("Enter");
  await expect(form).toContainText("共 3 个账号");
  await form.getByRole("button", { name: "添加监控", exact: true }).click();
  await expect(form).toContainText("稍后重试");
  expect(calls).toHaveLength(3);
  expect(new Set(calls.map(call => call.start)).size).toBe(1);
  expect(calls.every(call => call.interval_minutes === 60)).toBe(true);
  await expect(form.getByLabel("账号 1 用户名")).toHaveValue("@ALICE");
  fail = false;
  await form.getByRole("button", { name: "添加监控", exact: true }).click();
  await expect(form.getByLabel("账号 1 用户名")).toHaveValue("");
  expect(calls).toHaveLength(4);
  expect(calls[3].username).toBe("bob");
});
