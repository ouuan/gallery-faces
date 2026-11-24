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
  await expect(page.getByRole("link", { name: "X @alice", exact: true })).toHaveAttribute("href", "https://x.com/alice/");
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
  await expect(form.getByRole('checkbox', { name: '转发', exact: true })).toHaveCount(0);
  await form.locator(".publisher-cascader .n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option").filter({ has: page.locator(".n-cascader-option__label", { hasText: /^未分组$/ }) }).locator(".n-checkbox").click();
  await form.getByRole("heading", { name: "添加发布者" }).click();
  await expect(form.getByLabel("账号 1 用户名")).toHaveValue("");
  await form.getByLabel("账号 1 用户名").fill("@ALICE");
  await form.getByRole("button", { name: "添加账号", exact: true }).click();
  await form.getByLabel("账号 2 用户名").fill("bob");
  await form.getByRole("checkbox", { name: "指定起始时间，补拉历史" }).check();
  await form.getByLabel("起始时间", { exact: true }).fill("2020-01-01 12:34:56");
  await form.getByLabel("起始时间", { exact: true }).press("Enter");
  await expect(form).toContainText("共 3 项监控");
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


test("batch interval validates input, reports partial failure and refreshes saved values", async ({ page }) => {
  const items = [1, 2, 3].map(id => ({ id, platform: "x", username: `user${id}`, interval_minutes: 60, paused: id === 2 ? 1 : 0, active_task_id: null, next_check_at: "2026-11-19T00:00:00Z" }));
  const calls: any[] = [];
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/batch")) {
      const body = route.request().postDataJSON(); calls.push(body);
      items[0].interval_minutes = body.interval_minutes;
      return route.fulfill({ json: [{ id: 1, status: "updated" }, { id: 2, status: "error", error: "监控不存在" }] });
    }
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/monitors")) return route.fulfill({ json: items });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/monitors");
  await expect(page.getByRole("button", { name: "修改间隔", exact: true })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "选择 user1", exact: true }).check();
  await page.getByRole("checkbox", { name: "选择 user2", exact: true }).check();
  // A saved batch value must replace an older unsaved edit in the row.
  await page.locator(".monitor-list li").first().getByRole("textbox").fill("90");
  await page.getByRole("button", { name: "修改间隔", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("修改 2 项监控的间隔");
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  expect(calls).toHaveLength(0);
  await page.getByRole("button", { name: "修改间隔", exact: true }).click();
  await dialog.getByRole("textbox").fill("");
  await dialog.getByRole("textbox").press("Tab");
  await expect(dialog.getByRole("button", { name: "确认修改" })).toBeDisabled();
  await dialog.getByRole("textbox").fill("30");
  await dialog.getByRole("textbox").press("Tab");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
      await page.waitForTimeout(350);
      await page.screenshot({ path: `/tmp/gallery-faces/batch-interval-${width}-${theme}.png` });
    }
  }
  await dialog.getByRole("button", { name: "确认修改" }).click();
  await expect(dialog).not.toBeVisible();
  expect(calls).toEqual([{ action: "interval", ids: [1, 2], start: "", interval_minutes: 30 }]);
  await expect(page.getByRole("status")).toContainText("已修改检查间隔");
  await expect(page.getByRole("status")).toContainText("监控不存在");
  await expect(page.locator(".monitor-list li").first().getByRole("textbox")).toHaveValue("30");
  await expect(page.locator(".monitor-list li").nth(2).getByRole("textbox")).toHaveValue("60");
});

test("monitor layout preserves disclosure drafts and handles long content", async ({ page }) => {
  let empty = false;
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
    if (path.endsWith("/monitors")) return route.fulfill({ json: empty ? [] : [{ id: 1, platform: "instagram", username: "long_account_".repeat(8), interval_minutes: 60, paused: false, active_task_id: null, last_checked_at: null, next_check_at: "2026-11-19T00:00:00Z", last_result: "{}", last_error: "HTTPError:" + "abcdef0123456789".repeat(30) }] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/monitors");
  const form = page.locator(".monitor-create");
  const toggle = page.getByRole("button", { name: "添加发布者", exact: true });
  await expect(page.locator(".monitor-list li")).toHaveCount(1);
  await expect(form).toBeHidden();
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(form).toBeVisible();
  await expect(form.locator(".publisher-cascader")).toContainText("选择分组或搜索发布者");
  expect(await form.locator(".publisher-cascader").evaluate(el => el.contains(document.activeElement))).toBe(true);
  await form.getByLabel("账号 1 用户名").fill("draft_account");
  await page.getByRole("button", { name: "收起添加" }).click();
  await expect(toggle).toBeFocused();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(form).toBeHidden();
  await toggle.click();
  await expect(form.getByLabel("账号 1 用户名")).toHaveValue("draft_account");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(form).toBeVisible();
  for (const width of [390, 900, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
      await page.waitForTimeout(350);
      await page.screenshot({ path: `/tmp/gallery-faces/monitor-layout/after-expanded-${width}-${theme}.png`, fullPage: true });
    }
  }
  const selection = page.getByRole('checkbox', { name: '全选当前列表' });
  await selection.check();
  await form.getByRole('checkbox', { name: 'X', exact: true }).uncheck();
  await form.getByRole('checkbox', { name: '引用', exact: true }).check();
  await form.getByRole('button', { name: '添加账号', exact: true }).click();
  await form.getByLabel('Twitter List 链接').fill('invalid');
  await form.getByRole('button', { name: '添加标签' }).click();
  await form.getByRole('textbox', { name: '话题标签' }).fill('#摄影');
  await form.getByRole('textbox', { name: '话题标签' }).press('Enter');
  const interval = form.getByLabel('检查间隔（分钟）');
  await interval.fill('120');
  const history = form.getByRole('checkbox', { name: '指定起始时间，补拉历史' });
  await history.check();
  await form.getByRole('button', { name: '重置', exact: true }).click();
  await expect(form.getByLabel('账号 1 用户名')).toHaveValue('');
  await expect(form.getByLabel('账号 2 用户名')).toHaveCount(0);
  await expect(form.getByLabel('Twitter List 链接')).toHaveValue('');
  await expect(form.locator('.hashtag-field .n-tag')).toHaveCount(0);
  await expect(interval).toHaveValue('60');
  await expect(history).not.toBeChecked();
  await expect(form.getByRole('checkbox', { name: 'X', exact: true })).toBeChecked();
  await expect(form.getByRole('checkbox', { name: '引用', exact: true })).not.toBeChecked();
  await expect(form.getByRole('button', { name: '添加监控', exact: true })).toBeDisabled();
  await expect(selection).toBeChecked();
  await page.getByRole("button", { name: "收起添加" }).click();
  empty = true;
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.locator(".monitor-list li")).toHaveCount(0);
  await expect(form).toBeHidden();
  await page.reload();
  await expect(form).toBeVisible();
});


test("shared platform filter and canonical List batch", async ({ page }) => {
  const calls: any[] = [];
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/monitors") && route.request().method() === "POST") {
      calls.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: calls.length, task_id: calls.length } });
    }
    if (path.endsWith("/monitors")) return route.fulfill({ json: calls.map((call, i) => ({ ...call, id: i + 1, paused: 0 })) });
    if (path.endsWith('/monitors/1') && route.request().method() === 'PATCH') {
      Object.assign(calls[0], route.request().postDataJSON());
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/people")) return route.fulfill({ json: [1, 2].map(id => ({ id, name: `人物${id}`, groups: [], accounts: [{ platform: "x", username: `user${id}` }, { platform: "instagram", username: `user${id}` }] })) });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site")) return route.fulfill({ json: { site_title: "Gallery Faces" } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/monitors");
  const form = page.locator(".monitor-create");
  const instagram = form.getByRole("checkbox", { name: "Instagram", exact: true });
  const x = form.getByRole("checkbox", { name: "X", exact: true });
  await expect(instagram).toBeChecked();
  await expect(x).toBeChecked();
  await form.locator(".publisher-cascader .n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option").filter({ has: page.locator(".n-cascader-option__label", { hasText: /^未分组$/ }) }).locator(".n-checkbox").click();
  await form.getByRole("heading", { name: "添加发布者" }).click();
  await expect(form).toContainText("共 4 项监控");
  await instagram.uncheck();
  await expect(form).toContainText("共 2 项监控");
  await x.uncheck();
  const submit = form.getByRole("button", { name: "添加监控", exact: true });
  await expect(submit).toBeDisabled();
  await expect(form).toContainText("所选人物在这些平台没有关联账号");
  const quotes = form.getByRole('checkbox', { name: '引用', exact: true });
  await expect(quotes).toBeDisabled();
  await form.getByLabel('Twitter List 链接').fill('https://x.com/i/lists/123');
  await expect(quotes).toBeEnabled();
  await expect(form.getByRole('checkbox', { name: '快拍', exact: true })).toBeDisabled();
  await x.check();
  await form.getByLabel("Twitter List 链接").fill("https://x.com/i/lists/abc");
  await expect(submit).toBeDisabled();
  await form.getByLabel("Twitter List 链接").fill("https://twitter.com/i/lists/123?s=20\nhttps://x.com/i/lists/123/");
  await form.getByRole('button', { name: '添加标签' }).click();
  await form.getByRole('textbox', { name: '话题标签' }).fill('摄影 Live');
  await form.getByRole('textbox', { name: '话题标签' }).press('Tab');
  await expect(form).toContainText("共 3 项监控");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(400);
      await page.screenshot({ path: `/tmp/gallery-faces/list-platforms-${width}-${theme}.png`, fullPage: true });
    }
  }
  await submit.click();
  await expect(form.getByLabel("Twitter List 链接")).toHaveValue("");
  expect(calls.map(({ platform, username }) => ({ platform, username }))).toEqual([
    { platform: "x", username: "user1" }, { platform: "x", username: "user2" }, { platform: "x", username: "i/lists/123" },
  ]);
  expect(new Set(calls.map(call => call.start)).size).toBe(1);
  await expect(form).toContainText("Twitter List 123：已添加监控");
  expect(calls.map(call => call.hashtags)).toEqual(Array(3).fill(["摄影", "Live"]));
  await page.getByRole("button", { name: "修改标签" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator('.n-tag__content')).toHaveText(['摄影', 'Live']);
  await dialog.locator('.n-tag').filter({ hasText: '摄影' }).getByRole('button').click();
  await dialog.locator('.n-tag').filter({ hasText: 'Live' }).getByRole('button').click();
  const saved = page.waitForRequest(request => request.method() === "PATCH");
  await dialog.getByRole("button", { name: "确认修改" }).click();
  expect((await saved).postDataJSON()).toEqual({ hashtags: [] });
  const edit = page.getByRole('button', { name: '修改抓取范围' }).first();
  await edit.click();
  await expect(dialog.getByRole('checkbox', { name: '引用' })).not.toBeChecked();
  await dialog.getByRole('checkbox', { name: '引用' }).check();
  await dialog.getByRole('button', { name: '确认修改' }).click();
  await edit.click();
  await expect(dialog.getByRole('checkbox', { name: '引用' })).toBeChecked();
  await dialog.getByRole('button', { name: '取消' }).click();
  await expect(page.getByRole("link", { name: "Twitter List 123", exact: true })).toHaveAttribute("href", "https://x.com/i/lists/123/");
});
