import { expect } from '@playwright/test';
import { test } from '../room-fixture';

test('admin can inspect both matches from one room without uploading', async ({ guests }) => {
  const page = guests[1]!;
  await page.goto('/admin/game-matches');
  const result = await page.evaluate(async () => {
    async function request(path: string, body?: object, token?: string) {
      return fetch('/api/v1' + path, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', 'X-Gallery-Request': '1', ...(token && { 'X-Room-Token': token }) }, body: JSON.stringify(body) });
    }
    const unauthorized = (await request('/admin/game-matches')).status;
    const base = '/face-game/rooms';
    const host = await (await request(base, { nickname: '甲' })).json();
    const path = `${base}/${host.code}`;
    await request(path + '/join', { nickname: '乙' });
    let view = await (await request(path, undefined, host.token)).json();
    for (const action of ['start', 'finish', 'restart']) view = await (await request(path + '/actions', { action, stage: view.stage, match_id: view.match_id }, host.token)).json();
    await request('/login', { password: 'test-password' });
    return { unauthorized, code: host.code };
  });
  expect(result.unauthorized).toBe(401);
  await page.reload();
  const rooms = page.getByRole('button', { name: `认脸游戏 · ${result.code}` });
  await expect(rooms).toHaveCount(2);
  await rooms.last().click();
  await expect(page.getByText(/已结束 · 第 1 题/)).toBeVisible();
  await page.getByRole('button', { name: '返回对局列表' }).click();
  await rooms.first().click();
  await expect(page.getByRole('heading', { name: '玩家成绩' })).toBeVisible();
  await expect(page.getByText(/已结束 · 第 1 题/)).toHaveCount(0);
});

test('late answer messages leave the question in place on mobile and desktop', async ({ guests }) => {
  for (const page of guests.slice(0, 2)) {
    await page.goto('/face-game?t=90&grid=off');
    await page.getByRole('button', { name: '开始游戏' }).click();
    const choose = page.getByRole('button', { name: '都不是', exact: true });
    await expect(choose).toBeEnabled();
    await page.route('**/actions', async route => {
      if (route.request().postDataJSON().action === 'answer') await route.fulfill({ status: 409, json: { detail: '答题时间已到，本次答案未计入' } });
      else await route.fallback();
    });
    const board = page.locator('.game-frame');
    await choose.scrollIntoViewIfNeeded();
    const before = await board.boundingBox();
    await choose.click();
    await expect(page.getByText('答题时间已到，本次答案未计入')).toBeVisible();
    expect(await board.boundingBox()).toEqual(before);
  }
});
