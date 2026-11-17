import { test, expect } from "@playwright/test";

test("image actions use the current image unless images are checked", async ({ page }) => {
  const calls: { action: string; ids: number[] }[] = [];
  const images = [1, 2, 3].map((id) => ({ id, width: 800, height: 600, faces: [], sources: [], hidden: 0 }));
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#8799aa"/></svg>' });
    if (path.endsWith("/images/actions")) {
      const body = route.request().postDataJSON();
      calls.push(body);
      for (const image of images.filter((image) => body.ids.includes(image.id))) {
        if (body.action === "hide") image.hidden = 1;
        if (body.action === "show") image.hidden = 0;
      }
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/images")) return route.fulfill({ json: images });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/settings") || path.endsWith("/site")) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review");
  await page.getByRole("button", { name: "审核图片 2", exact: true }).click();
  await expect(page.getByText("当前图片 #2", { exact: true })).toBeVisible();
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.locator(".review-toolbar").screenshot({ path: `/tmp/gallery-faces/image-actions-${width}.png` });
  }
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "重新检测", exact: true }).click();
  expect(calls).toEqual([]);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "重新检测", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新检测", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "隐藏", exact: true }).click();
  await expect(page.getByRole("button", { name: "恢复可见", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "恢复可见", exact: true }).click();
  await expect(page.getByRole("button", { name: "隐藏", exact: true })).toBeEnabled();
  for (const action of ["重新检测", "隐藏"]) {
    await page.getByRole("checkbox", { name: "选择图片 1", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择图片 3", exact: true }).click();
    await expect(page.getByText("已选 2 张", { exact: true })).toBeVisible();
    await expect(page.getByText(/批量修正/)).toHaveCount(0);
    await page.getByRole("button", { name: action, exact: true }).click();
    await expect(page.getByText("当前图片 #2", { exact: true })).toBeVisible();
  }
  expect(calls).toEqual([
    { action: "redetect", ids: [2] }, { action: "hide", ids: [2] },
    { action: "show", ids: [2] }, { action: "redetect", ids: [1, 3] },
    { action: "hide", ids: [1, 3] },
  ]);
});
