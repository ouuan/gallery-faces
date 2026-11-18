import { test, expect } from "@playwright/test";

test("recycling expands the current image to its whole group and confirms the scope", async ({ page }) => {
  const calls: { action: string; ids: number[]; scope_token?: string }[] = [];
  let images = [1, 2, 3].map(id => ({ id, group_id: id === 2 ? 1 : id, width: 800, height: 600, faces: [], sources: [], hidden: 0 }));
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith("/images/recycle-preview")) {
      const { ids } = route.request().postDataJSON();
      const groups = new Set(images.filter(image => ids.includes(image.id)).map(image => image.group_id));
      const members = images.filter(image => groups.has(image.group_id)).map(image => image.id);
      return route.fulfill({ json: { groups: groups.size, total: members.length, ids: members, already_trashed: 0, scope_token: "scope-1" } });
    }
    if (path.endsWith("/images/actions")) {
      const body = route.request().postDataJSON();
      calls.push(body);
      if (body.action === "delete") {
        expect(body.scope_token).toBe("scope-1");
        images = images.filter(image => image.group_id !== 1);
        return route.fulfill({ json: { ok: true, deleted: 2, ids: [1, 2], cleanup_pending: 0 } });
      }
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/images")) return route.fulfill({ json: images });
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (/\/(settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review");
  await page.getByRole("button", { name: "审核图片 2", exact: true }).click();
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator(".review-toolbar").screenshot({ path: `/tmp/gallery-faces/image-actions-${width}.png` });
  }
  const recycle = page.getByRole("button", { name: "将当前重复组移入回收站", exact: true });
  await recycle.click();
  await expect(page.getByRole("dialog")).toContainText("1 组共 2 张图片");
  await expect(page.getByRole("dialog")).toContainText("包含同组的所有重复版本");
  await page.getByRole("dialog").getByRole("button", { name: "取消", exact: true }).click();
  expect(calls).toEqual([]);
  await recycle.click();
  await page.getByRole("dialog").getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("heading", { name: "图片 #3", exact: true })).toBeVisible();
  expect(calls).toEqual([{ action: "delete", ids: [2], scope_token: "scope-1" }]);
  await expect(page.getByRole("button", { name: "审核图片 1", exact: true })).toHaveCount(0);
});
