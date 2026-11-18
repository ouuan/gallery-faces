import { test, expect } from "@playwright/test";

test("review keyboard navigation, confirmation, deletion and input ownership", async ({ page }) => {
  page.on("pageerror", error => { throw error; });
  const images = [1, 2, 3].map(id => ({ id, width: 800, height: 600, detection: "done", sources: [{ id, platform: "x", author: "source", url: "https://x.com/source/status/1", published_at: "2026-01-01" }], faces: [{ id, revision: 0, box: [20, 20, 40, 40], person_id: 7, locked: false, ignored: false, candidates: [{ person_id: 7, score: 0.9 }, { person_id: 8, score: 0.8 }] }] }));
  const saved: number[] = [], deleted: number[][] = [];
  let fail = true;
  let release: (() => void) | undefined;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/") || path.endsWith("/crop")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (/\/admin\/faces\/\d+$/.test(path)) {
      const id = Number(path.split("/").pop()); saved.push(id);
      await new Promise<void>(resolve => { release = resolve; });
      Object.assign(images.find(i => i.id === id)!.faces[0]!, route.request().postDataJSON());
      return route.fulfill({ json: { ok: true } });
    }
    if (path.endsWith("/images/actions")) {
      if (fail) return route.fulfill({ status: 503, json: { detail: "删除失败测试" } });
      const body = route.request().postDataJSON(); expect(body.action).toBe("delete"); deleted.push(body.ids);
      for (let i = images.length - 1; i >= 0; i--) if (body.ids.includes(images[i]!.id)) images.splice(i, 1);
      return route.fulfill({ json: { deleted: body.ids.length, cleanup_pending: 0 } });
    }
    if (path.endsWith("/admin/images")) return route.fulfill({ json: images });
    if (path.endsWith("/feedback")) return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path.endsWith("/people")) return route.fulfill({ json: [7, 8].map(id => ({ id, name: `人物${id}`, groups: [], accounts: [] })) });
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (/\/(settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/review?state=all");
  const heading = page.locator(".review-heading > h3").first();
  await expect(heading).toHaveText("图片 #1");
  await page.keyboard.press("ArrowLeft"); await expect(heading).toHaveText("图片 #1");
  await page.keyboard.press("ArrowRight"); await expect(heading).toHaveText("图片 #2");
  await page.keyboard.press("c"); await expect.poll(() => saved.length).toBe(1);
  await page.keyboard.press("c"); await page.keyboard.press("ArrowRight"); await page.keyboard.press("d");
  await expect(heading).toHaveText("图片 #2"); await expect(page.getByRole("dialog")).toHaveCount(0);
  release!(); await expect(page.getByRole("button", { name: "全部确认", exact: true })).toBeDisabled();
  await expect(heading).toHaveText("图片 #2"); expect(saved).toEqual([2]);
  await page.getByRole("radio").first().focus(); await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio").nth(1)).toBeChecked(); await expect(heading).toHaveText("图片 #2");
  await page.getByRole("button", { name: "补全 / 编辑" }).click();
  await page.getByRole("dialog").getByRole("textbox").first().fill("cmdx");
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("d");
  await expect(heading).toHaveText("图片 #2"); await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.getByRole("button", { name: "取消", exact: true }).click(); await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("d");
  await expect(page.getByRole("dialog")).toContainText("#2");
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("c"); await page.keyboard.press("d");
  await expect(heading).toHaveText("图片 #2"); await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.getByRole("dialog").getByRole("button", { name: "取消" }).click(); await expect(page.getByRole("dialog")).toHaveCount(0); expect(deleted).toEqual([]);
  await page.keyboard.press("d"); await page.getByRole("dialog").getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByText("删除失败测试")).toBeVisible(); await expect(page.getByRole("dialog")).toHaveCount(0); fail = false;
  await page.keyboard.press("d"); await page.getByRole("dialog").getByRole("button", { name: "确认", exact: true }).click();
  await expect.poll(() => deleted).toEqual([[2]]);
  await expect(page.getByRole("button", { name: "删除当前图片", exact: true })).toBeEnabled();
  await page.getByRole("checkbox", { name: "选择图片 1", exact: true }).check();
  await page.getByRole("checkbox", { name: "选择图片 3", exact: true }).check();
  await page.getByRole("button", { name: "删除所选图片", exact: true }).focus();
  await page.keyboard.press("d"); await expect(page.getByRole("dialog")).toContainText("#1、#3");
  await page.getByRole("dialog").getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByText("没有需要处理的照片")).toBeVisible();
  await page.keyboard.press("d"); await page.keyboard.press("c"); await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(deleted).toEqual([[2], [1, 3]]);
});

test("duplicate shortcuts advance pairs and pause for details and requests", async ({ page }) => {
  page.on("pageerror", error => { throw error; });
  const image = (id: number) => ({ id, width: 800, height: 600, group_id: id, people: [], sources: [] });
  let rows = [1, 3].map(a => ({ a, b: a + 1, decision: "pending", score: 0.9, images: [image(a), image(a + 1)] }));
  const calls: unknown[] = []; let release: (() => void) | undefined;
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes("/media/")) return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"/>' });
    if (path.endsWith("/duplicates")) {
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON(); calls.push(body);
        await new Promise<void>(resolve => { release = resolve; }); rows = rows.filter(row => row.a !== body.a);
        return route.fulfill({ json: { ok: true } });
      }
      return route.fulfill({ json: rows });
    }
    if (path.endsWith("/session")) return route.fulfill({ json: { admin: true } });
    if (/\/(settings|site)$/.test(path)) return route.fulfill({ json: {} });
    return route.fulfill({ json: [] });
  });
  await page.goto("/admin/duplicates"); const heading = page.locator(".duplicate-heading");
  await expect(heading).toContainText("#1 与 #2");
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("ArrowRight"); await expect(heading).toContainText("#3 与 #4");
  await page.getByRole("button", { name: "查看图片 #3 详情" }).click();
  for (const key of ["ArrowLeft", "m", "x", "d"]) await page.keyboard.press(key);
  await expect(heading).toContainText("#3 与 #4"); expect(calls).toEqual([]);
  await page.keyboard.press("Escape"); await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("m"); await expect.poll(() => calls.length).toBe(1);
  for (const key of ["ArrowLeft", "m", "x"]) await page.keyboard.press(key);
  expect(calls).toEqual([{ a: 3, b: 4, action: "merge" }]); release!();
  await expect(page.getByRole("button", { name: "合并为一组" })).toBeEnabled();
  await expect(heading).toContainText("#1 与 #2");
  await page.keyboard.press("x"); await expect.poll(() => calls.length).toBe(2); release!();
  await expect(page.getByText("当前状态下暂无重复图片候选")).toBeVisible();
  expect(calls[1]).toEqual({ a: 1, b: 2, action: "separate" });
  await page.getByRole("link", { name: "识别审核", exact: true }).click();
  await expect(page.getByText("没有需要处理的照片")).toBeVisible();
  await page.keyboard.press("m"); await page.keyboard.press("x"); expect(calls).toHaveLength(2);
});
