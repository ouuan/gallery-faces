import { test, expect } from "@playwright/test";

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
    start: "2026-01-01", end: "2026-02-01", include_no_faces: "true", sort: "oldest",
  });
  await page.goto("/?" + query);
  const filters = page.locator(".desktop-filters");
  const start = filters.getByLabel("开始日期");
  const end = filters.getByLabel("结束日期");
  const noFaces = filters.getByRole("checkbox", { name: "包含无人脸图片" });
  const params = () => Object.fromEntries(new URL(page.url()).searchParams);
  const apiParams = () => Object.fromEntries(new URLSearchParams(requests.at(-1)));
  await expect(start).toHaveValue("2026-01-01");
  await expect(end).toHaveValue("2026-02-01");
  await expect(noFaces).toBeChecked();
  await expect(page.locator('[aria-label="排序"]')).toContainText("最早发布");
  await expect.poll(apiParams).toEqual(Object.fromEntries(query));

  // An unrelated filter update must not discard the saved matching mode.
  await start.fill("2026-01-02");
  const updated = { ...Object.fromEntries(query), start: "2026-01-02" };
  await expect.poll(params).toEqual(updated);
  await expect.poll(apiParams).toEqual(updated);
  await page.reload();
  await expect(start).toHaveValue("2026-01-02");
  await expect.poll(apiParams).toEqual(updated);

  await page.goBack();
  await expect(start).toHaveValue("2026-01-01");
  await expect.poll(apiParams).toEqual(Object.fromEntries(query));
  await page.goForward();
  await expect(start).toHaveValue("2026-01-02");
  await expect.poll(apiParams).toEqual(updated);

  await filters.getByRole("button", { name: "清空", exact: true }).click();
  await expect.poll(params).toEqual({});
  await expect.poll(apiParams).toEqual({});
  await expect(start).toHaveValue("");
  await expect(end).toHaveValue("");
  await expect(noFaces).not.toBeChecked();
  await expect(page.locator('[aria-label="排序"]')).toContainText("最新发布");
  await page.goBack();
  await expect.poll(params).toEqual(updated);
  await expect(start).toHaveValue("2026-01-02");
  await expect(noFaces).toBeChecked();
});
