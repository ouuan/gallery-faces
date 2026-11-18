import { test, expect } from "@playwright/test";

test("person editor stages all reference changes and preserves drafts on failure", async ({
  page,
}) => {
  const writes: any[] = [];
  let failSave = true;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/crop") || path.includes("/reference-media/"))
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="160"><rect width="200" height="160" fill="#8799aa"/></svg>',
      });
    if (
      path.endsWith("/admin/people/1") &&
      route.request().method() === "PUT"
    ) {
      writes.push(route.request().postDataJSON());
      return failSave
        ? route.fulfill({ status: 409, json: { detail: "保存失败，请重试" } })
        : route.fulfill({ json: { id: 1 } });
    }
    if (path.endsWith("/reference-upload"))
      return route.fulfill({
        json: {
          token: "a".repeat(32),
          width: 200,
          height: 160,
          faces: [
            { index: 0, box: [10, 10, 40, 40] },
            { index: 1, box: [90, 20, 40, 40] },
          ],
        },
      });
    if (path.endsWith("/references"))
      return route.fulfill({ json: [{ id: 5, face_id: 10 }] });
    if (path.endsWith("/confirmed-faces"))
      return route.fulfill({
        json: [
          { id: 10, image_id: 1, has_embedding: 1, is_reference: 1 },
          { id: 11, image_id: 2, has_embedding: 1, is_reference: 0 },
          { id: 12, image_id: 3, has_embedding: 0, is_reference: 0 },
        ],
      });
    if (path.endsWith("/people"))
      return route.fulfill({
        json: [
          {
            id: 1,
            name: "人物甲",
            groups: [],
            accounts: [],
            reference_count: 1,
            avatar_reference_id: 5,
          },
        ],
      });
    if (path.endsWith("/session"))
      return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/site") || path.endsWith("/settings"))
      return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/people");
  await expect(
    page.getByRole("button", { name: "参考图", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page
    .getByRole("button", { name: "删除参考图 #5", exact: true })
    .click();
  await page.getByRole("checkbox", { name: "#11" }).check();
  await expect(page.getByRole("checkbox", { name: "#12" })).toBeDisabled();
  expect(writes).toHaveLength(0);
  await page.addLocatorHandler(page.getByRole("dialog").filter({ hasText: "确认操作" }), async dialog => { await dialog.getByRole("button", { name: "确认", exact: true }).click(); }, { times: 1 });
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "#11" })).not.toBeChecked();
  await page
    .getByRole("button", { name: "删除参考图 #5", exact: true })
    .click();
  await page.getByRole("button", { name: "撤销删除 #5", exact: true }).click();
  await page
    .getByRole("button", { name: "删除参考图 #5", exact: true })
    .click();
  await page.getByRole("checkbox", { name: "#11" }).check();
  await page.locator('input[type="file"]').setInputFiles({
    name: "face.png",
    mimeType: "image/png",
    buffer: Buffer.from("fixture"),
  });
  await expect(page.getByRole("button", { name: "保存人物" })).toBeDisabled();
  await page.getByRole("button", { name: "选择人脸 2", exact: true }).click();
  expect(writes).toHaveLength(0);
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    await page
      .getByRole("dialog")
      .screenshot({ path: `/tmp/gallery-faces/people-edit-${width}.png` });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.getByRole("button", { name: "保存人物" }).click();
  await expect(page.getByText("保存失败，请重试")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "#11" })).toBeChecked();
  expect(writes[0]).toMatchObject({
    reference_face_ids: [11],
    removed_reference_ids: [5],
    uploaded_references: [{ token: "a".repeat(32), index: 1 }],
  });
  failSave = false;
  await page.getByRole("button", { name: "保存人物" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
