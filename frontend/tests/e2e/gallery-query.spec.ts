import { test, expect } from "@playwright/test";
test.use({ timezoneId: "UTC" });

test("mobile filter dismissals commit only changed drafts", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/gallery")) {
      requests.push(url.search);
      return route.fulfill({ json: { items: [], next_cursor: null } });
    }
    return route.fulfill({ json: /\/(people|groups)$/.test(url.pathname) ? [] : {} });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?match=all&sort=oldest");
  await expect.poll(() => requests.length).toBe(1);
  const drawer = page.getByRole("dialog", { name: "筛选照片", exact: true });
  const open = () => page.getByRole("button", { name: "筛选", exact: true }).click();
  const params = () => Object.fromEntries(new URL(page.url()).searchParams);
  const apiParams = () => Object.fromEntries(new URLSearchParams(requests.at(-1)));
  const original = { match: "all", sort: "oldest" };
  await open();
  await expect(drawer.getByRole("heading", { name: "筛选照片", exact: true })).toHaveCount(1);
  await expect(drawer.getByRole("button", { name: "应用筛选" })).toBeVisible();
  await drawer.getByLabel("开始时间").fill("2026-01-02 00:00:00");
  await drawer.getByLabel("开始时间").press("Enter");
  await drawer.getByRole("checkbox", { name: "包含无人脸图片" }).check();
  expect(params()).toEqual(original);
  expect(requests).toHaveLength(1);
  await page.mouse.click(375, 400);
  await expect(drawer).toBeHidden();
  const applied = { ...original, start: "2026-01-02T00:00:00Z", include_no_faces: "true" };
  await expect.poll(params).toEqual(applied);
  await expect.poll(apiParams).toEqual(applied);
  expect(requests).toHaveLength(2);

  await open();
  await expect(drawer.getByLabel("开始时间")).toHaveValue("2026-01-02 00:00:00");
  await expect(drawer.getByRole("checkbox", { name: "包含无人脸图片" })).toBeChecked();
  await drawer.getByRole("button", { name: "应用筛选" }).click();
  await expect(drawer).toBeHidden();
  expect(requests).toHaveLength(2);

  await open();
  await drawer.getByRole("button", { name: "清空", exact: true }).click();
  expect(params()).toEqual(applied);
  expect(requests).toHaveLength(2);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect.poll(params).toEqual({ sort: "oldest" });
  await expect.poll(apiParams).toEqual({ sort: "oldest" });
  expect(requests).toHaveLength(3);
  await open();
  await expect(drawer.getByLabel("开始时间")).toHaveValue("");
  await expect(drawer.getByRole("checkbox", { name: "包含无人脸图片" })).not.toBeChecked();
});

test("gallery query restores filters, follows history and clears applied filters", async ({ page }) => {
  const requests: string[] = [];
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/gallery")) {
      requests.push(url.search);
      return route.fulfill({ json: { items: [], next_cursor: null } });
    }
    if (url.pathname.endsWith("/people")) return route.fulfill({ json: [
      { id: 1, name: "人物甲", groups: [], accounts: [] },
      { id: 2, name: "人物乙", groups: [], accounts: [] },
    ] });
    return route.fulfill({ json: url.pathname.endsWith("/groups") ? [] : {} });
  });
  await page.setViewportSize({ width: 1280, height: 900 });
  const query = new URLSearchParams({
    people: "1", match: "all", publishers: "x:someone",
    start: "2026-01-01T00:00:00Z", end: "2026-02-01T00:00:00Z", include_no_faces: "true", sort: "oldest",
  });
  await page.goto("/?" + query);
  const filters = page.locator(".desktop-filters");
  const start = filters.getByLabel("开始时间");
  const end = filters.getByLabel("结束时间");
  const noFaces = filters.getByRole("checkbox", { name: "包含无人脸图片" });
  const params = () => Object.fromEntries(new URL(page.url()).searchParams);
  const apiParams = () => Object.fromEntries(new URLSearchParams(requests.at(-1)));
  await expect(start).toHaveValue("2026-01-01 00:00:00");
  await expect(end).toHaveValue("2026-02-01 00:00:00");
  await expect(noFaces).toBeChecked();
  await expect(page.locator('[aria-label="排序"]')).toContainText("最早发布");
  await expect.poll(apiParams).toEqual(Object.fromEntries(query));

  // An unrelated filter update must not discard the saved matching mode.
  await start.fill("2026-01-02 00:00:00");
  await start.press("Enter");
  const updated = { ...Object.fromEntries(query), start: "2026-01-02T00:00:00Z" };
  await expect.poll(params).toEqual(updated);
  await expect.poll(apiParams).toEqual(updated);
  await page.reload();
  await expect(start).toHaveValue("2026-01-02 00:00:00");
  await expect.poll(apiParams).toEqual(updated);

  await page.goBack();
  await expect(start).toHaveValue("2026-01-01 00:00:00");
  await expect.poll(apiParams).toEqual(Object.fromEntries(query));
  await page.goForward();
  await expect(start).toHaveValue("2026-01-02 00:00:00");
  await expect.poll(apiParams).toEqual(updated);

  await filters.getByRole("button", { name: "清空", exact: true }).click();
  await expect.poll(params).toEqual({ sort: "oldest" });
  await expect.poll(apiParams).toEqual({ sort: "oldest" });
  await expect(start).toHaveValue("");
  await expect(end).toHaveValue("");
  await expect(noFaces).not.toBeChecked();
  await expect(page.locator('[aria-label="排序"]')).toContainText("最早发布");
  await page.goBack();
  await expect.poll(params).toEqual(updated);
  await expect(start).toHaveValue("2026-01-02 00:00:00");
  await expect(noFaces).toBeChecked();
});
