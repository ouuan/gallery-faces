import { expect } from '@playwright/test';
import { test } from '../room-fixture';

test('admin refreshes the current filtered snapshot manually', async ({ guests }) => {
  const page = guests[0]!;
  const start = new Date('2026-11-28T04:00:00Z');
  await page.clock.install({ time: start });
  await page.clock.setFixedTime(new Date(start.valueOf() + 1000));
  const requests: URLSearchParams[] = [];
  await page.route('**/api/v1/admin/game-matches?*', async route => {
    requests.push(new URL(route.request().url()).searchParams);
    if (requests.length === 2) return route.fulfill({ status: 503, json: { detail: '暂时不可用' } });
    return route.fulfill({ json: { total: 21, items: [{ id: 'example', code: 'ABCD', game: 'face-game', solo: false,
      phase: requests.length === 1 ? 'answer' : 'reveal', round: 1, members: 2, activity: start.toISOString() }] } });
  });
  const path = '/admin/game-matches?game=face-game&mode=multi&phase=active&page=2';
  await page.goto(path);
  await page.getByPlaceholder('输入管理员密码').fill('test-password');
  await page.getByRole('button', { name: '登录工作台' }).click();
  const time = page.locator('.matches time');
  await expect(time).toHaveText('1秒前');
  await page.clock.fastForward(10_000);
  await page.clock.setFixedTime(new Date(start.valueOf() + 11_000));
  await page.clock.runFor(1000);
  await expect(time).toHaveText('1秒前');
  expect(requests).toHaveLength(1);
  const refresh = page.getByRole('button', { name: '刷新', exact: true });
  await expect(refresh).toBeVisible();
  await refresh.click();
  await expect(page.getByRole('alert')).toContainText('暂时不可用');
  await expect(time).toHaveText('1秒前');
  await refresh.click();
  await expect(time).toHaveText('11秒前');
  await expect(page.getByText('答案揭晓 · 第 1 题')).toBeVisible();
  expect(requests.map(params => Object.fromEntries(params))).toEqual(Array(3).fill({ game: 'face-game', mode: 'multi', phase: 'active', page: '2' }));
  await page.locator('.match-filters').getByText('进行中', { exact: true }).click();
  await page.locator('.n-base-select-option').getByText('已结束', { exact: true }).click();
  await expect(page).toHaveURL('/admin/game-matches?game=face-game&mode=multi&phase=finished');
  await page.goBack();
  await expect(page).toHaveURL(path);
  await expect(page.locator('.match-filters')).toContainText('进行中');
});

test('admin sees the unfilled nickname and accuracy of a solo grid player', async ({ guests }) => {
  const player = guests[0]!, admin = guests[1]!;
  await player.goto('/face-game?people=1,2&t=90');
  await player.getByRole('button', { name: '开始游戏' }).click();
  await expect(player.getByRole('button', { name: '结束本局' })).toBeVisible();
  await admin.goto('/admin/game-matches');
  await admin.getByPlaceholder('输入管理员密码').fill('test-password');
  await admin.getByRole('button', { name: '登录工作台' }).click();
  await admin.getByRole('link', { name: '认脸游戏 · 单人' }).click();
  await expect(admin.getByText('未填写昵称', { exact: true })).toBeVisible();
  await expect(admin.getByText('答对时平均 —', { exact: true })).toBeVisible();
  await expect(admin.getByText('正确率 —', { exact: true })).toBeVisible();
  await player.getByRole('button', { name: '人1', exact: true }).click();
  const averageCells = player.getByRole('group', { name: '本局统计' }).getByText(/^答对时平均 \d+\.\d 格$/);
  await expect(averageCells).toBeVisible();
  await admin.reload();
  await expect(admin.getByText(await averageCells.innerText(), { exact: true })).toBeVisible();
  await expect(admin.getByText('正确率 100%', { exact: true })).toBeVisible();
  await expect(admin.locator('.player-result').getByText(/分$/)).toHaveCount(0);
});

test('admin sees the same deviation as a solo history player without points', async ({ guests }) => {
  const player = guests[0]!, admin = guests[1]!;
  await player.goto('/history-quiz');
  await player.getByRole('button', { name: '开始游戏' }).click();
  await player.getByRole('button', { name: '提交日期' }).click();
  const deviation = player.getByRole('group', { name: '本局统计' }).getByText(/^平均偏差 .* 天$/);
  await expect(deviation).toBeVisible();
  await admin.goto('/admin/game-matches');
  await admin.getByPlaceholder('输入管理员密码').fill('test-password');
  await admin.getByRole('button', { name: '登录工作台' }).click();
  await admin.getByRole('link', { name: '史官测验 · 单人' }).click();
  const result = admin.locator('.player-result');
  await expect(result.getByText(await deviation.innerText(), { exact: true })).toBeVisible();
  await expect(result.getByText(/分$/)).toHaveCount(0);
});

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
    const firstMatch = view.match_id;
    for (const action of ['start', 'finish', 'restart']) view = await (await request(path + '/actions', { action, stage: view.stage, match_id: view.match_id }, host.token)).json();
    await request('/login', { password: 'test-password' });
    return { unauthorized, code: host.code, firstMatch, secondMatch: view.match_id };
  });
  expect(result.unauthorized).toBe(401);
  const query = '?game=face-game&mode=multi';
  await page.goto('/admin/game-matches' + query);
  const rooms = page.getByRole('link', { name: `认脸游戏 · ${result.code}` });
  await expect(rooms).toHaveCount(2);
  await rooms.last().click();
  await expect(page).toHaveURL(`/admin/game-matches/${result.firstMatch}${query}`);
  await page.reload();
  await expect(page.getByText(/已结束 · 第 1 题/)).toBeVisible();
  for (const label of ['创建时间', '最后活动时间']) {
    await expect(page.getByText(new RegExp(`^${label}：\\d{4}/\\d{2}/\\d{2} \\d{2}:\\d{2}:\\d{2}$`))).toBeVisible();
  }
  await page.goBack();
  await expect(page).toHaveURL('/admin/game-matches' + query);
  await page.goForward();
  await expect(page.getByText(/已结束 · 第 1 题/)).toBeVisible();
  await page.getByRole('link', { name: '返回对局列表' }).click();
  await rooms.first().click();
  await expect(page).toHaveURL(`/admin/game-matches/${result.secondMatch}${query}`);
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
