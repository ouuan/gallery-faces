import { test, expect } from "@playwright/test";

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
  await expect(
    page.getByRole("button", { name: "导入照片", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("checkbox", { name: "选择人物 人物丙" }).check();
  await page.getByRole("button", { name: "导入照片", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "创建导入任务" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "取消" }).click();
  await page.getByRole("checkbox", { name: "全选", exact: true }).check();
  await page.getByRole("button", { name: "导入照片", exact: true }).click();
  await expect(dialog).toContainText("将跳过：人物丙");
  await expect(dialog.locator(".account-list li")).toHaveCount(2);
  await dialog.getByLabel("开始日期", { exact: true }).fill("2026-11-18");
  await dialog.getByLabel("结束日期（含当天）").fill("2026-11-17");
  await expect(
    dialog.getByRole("button", { name: "创建导入任务" }),
  ).toBeDisabled();
  await dialog.getByLabel("结束日期（含当天）").fill("2026-11-18");
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("html")).toHaveJSProperty("scrollWidth", width);
    await page.screenshot({
      path: `/tmp/gallery-faces/people-import-${width}.png`,
    });
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.waitForTimeout(350);
  await page.screenshot({ path: "/tmp/gallery-faces/people-import-dark.png" });
  await dialog.getByRole("button", { name: "创建导入任务" }).click();
  await expect(
    dialog.getByRole("button", { name: "创建导入任务" }),
  ).toBeDisabled();
  await expect(dialog).toContainText("网络错误，请重试");
  await expect(dialog.getByLabel("开始日期", { exact: true })).toHaveValue(
    "2026-11-18",
  );
  fail = false;
  await dialog.getByRole("button", { name: "创建导入任务" }).click();
  await expect(dialog).toContainText("已创建 1 个任务，复用 1 个任务");
  expect(requests).toHaveLength(2);
  expect(requests[1]).toEqual({
    urls: ["https://x.com/alice", "https://instagram.com/alice"],
    start: "2026-11-18",
    end: "2026-11-18",
  });
  await expect(page).toHaveURL(/\/admin\/people$/);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "全选", exact: true }),
  ).toBeChecked();
  await page.getByRole("button", { name: "导入照片", exact: true }).click();
  await expect(dialog.getByLabel("开始日期", { exact: true })).toHaveValue("");
  await dialog.getByRole("button", { name: "取消" }).click();
  await page.getByRole("button", { name: "清空选择" }).click();
  await expect(
    page.getByRole("button", { name: "导入照片", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("checkbox", { name: "全选", exact: true }).check();
  await page.getByRole("button", { name: "分组", exact: true }).click();
  await page.getByRole("button", { name: "人物", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "全选", exact: true }),
  ).not.toBeChecked();
  await page.getByRole("checkbox", { name: "全选", exact: true }).check();
  await page.getByRole("button", { name: "导入照片", exact: true }).click();
  await dialog.getByRole("button", { name: "创建导入任务" }).click();
  await dialog.getByRole("button", { name: "查看导入任务" }).click();
  await expect(page).toHaveURL(/\/admin\/import$/);
  expect(requests[2].start).toBe("");
  expect(requests[2].end).toBe("");
});
