import { expect, test } from "@playwright/test";

test("people groups expand independently and load avatars only for visible members", async ({ page }) => {
  const groups = [{ id: 1, name: "朋友" }, { id: 2, name: "同事" }];
  const people = [
    { id: 1, name: "共同成员", groups },
    { id: 2, name: "同事甲", groups: [groups[1]] },
    { id: 3, name: "独立人物", groups: [] },
  ].map(person => ({ ...person, accounts: [], reference_count: 1, avatar_reference_id: person.id }));
  const crops = new Set<number>();
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname;
    const crop = path.match(/\/references\/(\d+)\/crop$/);
    if (crop) {
      crops.add(Number(crop[1]));
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"/>' });
    }
    if (path.endsWith("/people")) return route.fulfill({ json: people });
    if (path.endsWith("/groups")) return route.fulfill({ json: groups });
    return route.fulfill({ json: /\/(session|site|settings)$/.test(path) ? {} : [] });
  });
  await page.goto("/admin/people");
  const friends = page.getByRole("button", { name: "朋友 1 人" });
  const colleagues = page.getByRole("button", { name: "同事 2 人" });
  const ungrouped = page.getByRole("button", { name: "未分组 1 人" });
  const shared = page.getByRole("heading", { name: "共同成员" });
  await expect(friends).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".person-row")).toHaveCount(0);
  expect(crops.size).toBe(0);
  await friends.press("Enter");
  await expect(shared).toHaveCount(1);
  await expect.poll(() => [...crops]).toEqual([1]);
  await colleagues.click();
  await expect(shared).toHaveCount(2);
  await expect.poll(() => [...crops]).toEqual([1, 2]);
  await friends.press("Space");
  await expect(shared).toHaveCount(1);
  await expect(page.locator("#people-group-1")).toHaveCount(0);
  await page.getByRole("button", { name: "分组", exact: true }).press("Enter");
  await expect(page.getByRole("button", { name: "分组", pressed: true, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "人物", exact: true }).press("Space");
  await expect(friends).toHaveAttribute("aria-expanded", "false");
  await expect(colleagues).toHaveAttribute("aria-expanded", "true");
  await ungrouped.click();
  await expect(page.getByRole("heading", { name: "独立人物" })).toBeVisible();
});
