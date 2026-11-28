import { expect, test } from '@playwright/test';

for (const width of [390, 1280]) {
  test(`select, confirm, delete and restore face boxes at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const faces = [1, 2, 3].map(id => ({ id, person_id: 7, locked: false, ignored: false,
      revision: 0, box: [id * 120, 50, 80, 80], candidates: [] }));
    const batches: number[][] = [];
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/admin/faces')) {
        const edits = route.request().postDataJSON().faces;
        const saved = edits.map((edit: { id: number }) => edit.id);
        batches.push(saved);
        for (const edit of edits) Object.assign(faces.find(face => face.id === edit.id)!, edit, { revision: edit.revision + 1 });
        return route.fulfill({ json: { saved, failures: [] } });
      }
      if (path.endsWith('/restore')) {
        const face = faces.find(face => path.includes(`/faces/${face.id}/`))!;
        expect(route.request().postDataJSON()).toEqual({ revision: face.revision });
        Object.assign(face, { ignored: false, locked: true, person_id: 7, revision: face.revision + 1 });
        return route.fulfill({ json: { ok: true } });
      }
      if (path.includes('/media/') || path.endsWith('/crop')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#8799aa"/></svg>' });
      if (path.endsWith('/images')) return route.fulfill({ json: [{ id: 1, width: 640, height: 480, faces, sources: [] }] });
      if (path.endsWith('/session')) return route.fulfill({ json: { admin: true } });
      if (path.endsWith('/people')) return route.fulfill({ json: [{ id: 7, name: '测试人物', groups: [], accounts: [] }] });
      if (path.endsWith('/feedback')) return route.fulfill({ json: { items: [], next_cursor: null } });
      if (path.endsWith('/site') || path.endsWith('/settings')) return route.fulfill({ json: {} });
      return route.fulfill({ json: [] });
    });
    await page.goto('/admin/review?state=image&image=1');
    const deleted = page.getByRole('button', { name: /查看已删除/ });
    const check = (index: number) => page.getByRole('checkbox', { name: `人脸 #${index}`, exact: true });
    await expect(check(1)).toBeVisible();
    await expect(deleted).toHaveCount(0);
    await check(1).check();
    await check(3).check();
    await expect(page.getByRole('button', { name: '全部确认' })).toHaveCount(0);
    await page.locator('.review-faces').screenshot({ path: `/tmp/gallery-faces/batch-faces-${width}.png` });
    await page.getByRole('button', { name: '批量确认' }).click();
    await expect(page.getByRole('button', { name: '全部确认' })).toBeEnabled();
    expect(batches).toEqual([[1, 3]]);
    await page.getByRole('checkbox', { name: '全选人脸' }).check();
    await check(2).uncheck();
    await page.getByRole('button', { name: '批量删除' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '取消' }).click();
    expect(batches).toHaveLength(1);
    await page.getByRole('button', { name: '批量删除' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确认' }).click();
    await expect(deleted).toHaveText('查看已删除（2）');
    expect(batches[1]).toEqual([1, 3]);
    await expect(page.locator('.face-box')).toHaveCount(1);
    await deleted.click();
    await expect(page.locator('.face-box.ignored')).toHaveCount(2);
    await page.locator('.review-faces').screenshot({ path: `/tmp/gallery-faces/deleted-faces-${width}.png` });
    await page.getByRole('button', { name: '恢复人脸框 #2' }).click();
    await expect(page.locator('.face-box.ignored')).toHaveCount(1);
    await page.getByRole('button', { name: '恢复人脸框 #1' }).click();
    await expect(check(3)).toBeVisible();
    await expect(deleted).toHaveCount(0);
    await expect(page.locator('.face-box')).toHaveCount(3);
  });
}
