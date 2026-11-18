import { test, expect } from "@playwright/test";
test.use({ timezoneId: "UTC" });

test("batch imports associated accounts and preserves input on failure", async ({
  page,
}) => {
  const requests: any[] = [];
  let fail = true;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/admin/import")) {
      requests.push(route.request().postDataJSON());
      await new Promise((resolve) => setTimeout(resolve, 150));
      return route.fulfill(
        fail
          ? { status: 503, json: { detail: "网络错误，请重试" } }
          : {
              json: [
                { value: "https://x.com/alice", status: "queued", task_id: 1 },
                {
                  value: "https://instagram.com/alice",
                  status: "duplicate",
                  task_id: 2,
                },
              ],
            },
      );
    }
    if (path.endsWith("/people"))
      return route.fulfill({
        json: [
          {
            id: 1,
            name: "人物甲",
            groups: [],
            accounts: [
              { platform: "x", username: "Alice" },
              { platform: "instagram", username: "alice" },
            ],
            reference_count: 0,
          },
          {
            id: 2,
            name: "人物乙",
            groups: [],
            accounts: [{ platform: "x", username: "alice" }],
            reference_count: 0,
          },
          {
            id: 3,
            name: "人物丙",
            groups: [],
            accounts: [],
            reference_count: 0,
          },
        ],
      });
    if (path.endsWith("/tasks"))
      return route.fulfill({ json: { items: [], total: 0, page: 1 } });
    if (path.endsWith("/site") || path.endsWith("/settings"))
      return route.fulfill({ json: { timezone: "Asia/Shanghai" } });
    if (path.endsWith("/session"))
      return route.fulfill({ json: { admin: true } });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/people");
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.goto("/admin/import");
  const picker = page.locator(".publisher-cascader");
  await picker.locator(".n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option").filter({ has: page.locator(".n-cascader-option__label", { hasText: /^未分组$/ }) }).locator(".n-checkbox").click();
  await page.getByRole("heading", { name: "导入任务", exact: true }).click();
  const links = page.getByRole("textbox", { name: "链接，每行一个" });
  await expect(links).toHaveValue("");
  await links.fill("https://www.twitter.com/Alice/\nhttps://x.com/bob");
  await page.getByLabel("开始时间", { exact: true }).fill("2026-11-18 00:00:00");
  await page.getByLabel("开始时间", { exact: true }).press("Enter");
  await page.getByLabel("结束时间（不含）").fill("2026-11-17 00:00:00");
  await page.getByLabel("结束时间（不含）").press("Enter");
  const submit = page.getByRole("button", { name: "创建导入任务" });
  await expect(submit).toBeDisabled();
  await page.getByLabel("结束时间（不含）").fill("2026-11-19 00:00:00");
  await page.getByLabel("结束时间（不含）").press("Enter");
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
    await page.screenshot({ path: `/tmp/gallery-faces/people-import-${width}.png` });
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.waitForTimeout(350);
  await page.screenshot({ path: "/tmp/gallery-faces/people-import-dark.png" });
  await submit.click();
  await expect(page.getByText("网络错误，请重试")).toBeVisible();
  await expect(links).toHaveValue("https://www.twitter.com/Alice/\nhttps://x.com/bob");
  await expect(picker).toContainText("未分组");
  fail = false;
  await submit.click();
  await expect(page.getByText("已加入队列", { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual({
    urls: ["https://x.com/alice", "https://instagram.com/alice", "https://x.com/bob"],
    directory: null,
    start: "2026-11-18T00:00:00Z",
    end: "2026-11-19T00:00:00Z",
  });
});
