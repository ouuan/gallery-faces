import { test, expect } from "@playwright/test";

test('confirm all saves current choices and retries only failed faces', async ({ page }) => {
  const faces = [
    { id: 1, person_id: 7, locked: false, ignored: false },
    { id: 2, person_id: null, locked: false, ignored: false },
    { id: 3, person_id: 7, locked: true, ignored: false },
    { id: 4, person_id: null, locked: false, ignored: false },
    { id: 5, person_id: 7, locked: true, ignored: true },
  ].map(face => ({ ...face, revision: 3, box: [20, 20, 40, 40], candidates: [{ person_id: 8, score: 0.9 }] }));
  const saved: { id: number; person_id: number; revision: number; locked: boolean }[] = [];
  const batches: number[][] = [];
  let failed = false;
  let release: (() => void) | undefined;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/") || path.endsWith("/crop"))
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (path.endsWith("/admin/faces")) {
      expect(route.request().method()).toBe("PUT");
      const { faces: edits } = route.request().postDataJSON();
      batches.push(edits.map((face: { id: number }) => face.id));
      await gate;
      const result = { saved: [] as number[], failures: [] as { id: number; detail: string; status: number }[] };
      for (const { id, ...body } of edits) {
        if (id === 2 && !failed) {
          failed = true;
          result.failures.push({ id, detail: "人脸已更新，请刷新后再操作", status: 409 });
          continue;
        }
        saved.push({ id, person_id: body.person_id, revision: body.revision, locked: body.locked });
        Object.assign(faces.find(face => face.id === id)!, body, { revision: body.revision + 1 });
        result.saved.push(id);
      }
      return route.fulfill({ json: result });
    }
    if (path.endsWith("/admin/images")) return route.fulfill({ json: [1, 2].map(id => ({ id, width: 800, height: 600, detection: "done", faces: id === 1 ? faces : [{ ...faces[0], id: 6 }], sources: [] })) });
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (path.endsWith("/people")) return route.fulfill({ json: [7, 8].map(id => ({ id, name: `人物${id}`, groups: [], accounts: [] })) });
    if (path.endsWith("/site") || path.endsWith("/settings")) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review?state=image&image=1");
  await page.locator('.face-review').nth(1).locator('label').filter({ has: page.getByRole('radio', { name: /人物8/ }) }).click();
  const all = page.getByRole('button', { name: '全部确认', exact: true });
  await all.click();
  await expect(all).toBeDisabled();
  await expect(page.getByRole('button', { name: '下一张', exact: true })).toBeDisabled();
  await expect(page.locator('.face-review').first().getByRole('button', { name: '确认', exact: true })).toBeDisabled();
  await expect(page.getByRole('radio').first()).toBeDisabled();
  release!();
  await expect(page.getByText(/已确认 1 个人脸，1 个失败/)).toBeVisible();
  await expect(all).toBeEnabled();
  await expect(page.locator('.face-review').nth(1).locator('.n-cascader')).toContainText('人物8');
  await all.click();
  await expect.poll(() => saved.length).toBe(2);
  await expect(page.locator(".review-faces .n-button--loading")).toHaveCount(0);
  await expect(all).toBeDisabled();
  expect(batches).toEqual([[1, 2], [2]]);
  expect(saved).toEqual([
    { id: 1, person_id: 7, revision: 3, locked: true },
    { id: 2, person_id: 8, revision: 3, locked: true },
  ]);
});
