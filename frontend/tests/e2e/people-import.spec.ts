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
  await expect(page.getByRole('checkbox', { name: '转发', exact: true })).toBeDisabled();
  const picker = page.locator(".publisher-cascader");
  await picker.locator(".n-base-selection").click();
  await page.locator(".people-cascader-menu .n-cascader-option").filter({ has: page.locator(".n-cascader-option__label", { hasText: /^未分组$/ }) }).locator(".n-checkbox").click();
  await page.getByRole("heading", { name: "导入任务", exact: true }).click();
  const links = page.getByRole("textbox", { name: "链接，每行一个" });
  const x = page.getByRole("checkbox", { name: "X", exact: true });
  const instagram = page.getByRole("checkbox", { name: "Instagram" });
  await expect(x).toBeChecked();
  await expect(instagram).toBeChecked();
  for (const name of ['快拍', 'tagged']) await expect(page.getByRole('checkbox', { name, exact: true })).toBeChecked();
  for (const name of ['转推', '引用', '转发']) await expect(page.getByRole('checkbox', { name, exact: true })).not.toBeChecked();
  await expect(links).toHaveValue("");
  await links.fill("https://www.twitter.com/Alice/\nhttps://x.com/bob");
  await page.getByRole('button', { name: '添加标签' }).click();
  const tagInput = page.getByRole('textbox', { name: '话题标签' });
  await tagInput.fill('#摄影，Live、摄影');
  await tagInput.press('Enter');
  await expect(page.locator('.hashtag-field .n-tag__content')).toHaveText(['摄影', 'Live']);
  expect(requests).toHaveLength(0);
  await page.getByLabel("开始时间", { exact: true }).fill("2026-11-18 00:00:00");
  await page.getByLabel("开始时间", { exact: true }).press("Enter");
  await page.getByLabel("结束时间（不含）").fill("2026-11-17 00:00:00");
  await page.getByLabel("结束时间（不含）").press("Enter");
  const submit = page.getByRole("button", { name: "创建导入任务" });
  await expect(submit).toBeDisabled();
  const reposts = page.getByRole('checkbox', { name: '转发', exact: true });
  await reposts.check();
  await expect(page.getByLabel('开始时间', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('结束时间（不含）')).toBeDisabled();
  await expect(page.getByText('包含 Instagram 转发时，不能按日期筛选')).toBeVisible();
  await submit.click();
  await expect(page.getByText('网络错误，请重试')).toBeVisible();
  expect(requests[0].scope.reposts).toBe(true);
  expect(requests[0]).not.toHaveProperty('start');
  expect(requests[0]).not.toHaveProperty('end');
  await reposts.uncheck();
  await expect(submit).toBeDisabled();
  await expect(page.getByLabel('开始时间', { exact: true })).toHaveValue('2026-11-18 00:00:00');
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
  expect(requests).toHaveLength(3);
  expect(requests.at(-1)).toEqual({
    scope: { retweets: false, quoted: false, stories: true, tagged: true, reposts: false },
    urls: ["https://x.com/alice", "https://instagram.com/alice", "https://x.com/bob"],
    directory: null,
    hashtags: ["摄影", "Live"],
    start: "2026-11-18T00:00:00Z",
    end: "2026-11-19T00:00:00Z",
  });
  await links.fill("");
  await x.uncheck();
  await instagram.uncheck();
  await expect(submit).toBeDisabled();
  await expect(page.getByRole("status").filter({ hasText: "没有匹配的发布者账号" })).toBeVisible();
  await links.fill("https://x.com/bob");
  await expect(submit).toBeEnabled();
  await instagram.check();
  await submit.click();
  await expect.poll(() => requests.at(-1).urls).toEqual(["https://instagram.com/alice", "https://x.com/bob"]);
  await expect(submit).toBeEnabled();
  await instagram.uncheck();
  await links.fill('https://instagram.com/bob');
  await reposts.check();
  await links.fill('https://instagram.com/p/abc');
  await expect(reposts).toBeDisabled();
  await expect(reposts).toBeChecked();
  await expect(page.getByLabel('开始时间', { exact: true })).toBeEnabled();
  await submit.click();
  await expect.poll(() => requests.at(-1).scope).toEqual({});
  await expect(submit).toBeEnabled();
  expect(requests.at(-1).start).toBe('2026-11-18T00:00:00Z');
  await links.fill('https://instagram.com/bob');
  await expect(reposts).toBeEnabled();
  await expect(page.getByLabel('开始时间', { exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'tagged', exact: true }).uncheck();
  const importCount = requests.length;
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(links).toHaveValue('');
  await expect(page.locator('.hashtag-field .n-tag')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '添加标签' })).toBeDisabled();
  await expect(page.getByLabel('开始时间', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('结束时间（不含）')).toHaveValue('');
  await expect(x).toBeChecked();
  await expect(instagram).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'tagged', exact: true })).toBeChecked();
  await expect(reposts).not.toBeChecked();
  await expect(reposts).toBeDisabled();
  await expect(submit).toBeDisabled();
  expect(requests).toHaveLength(importCount);
});
