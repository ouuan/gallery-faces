import { expect } from '@playwright/test';
import { test } from '../room-fixture';

test.use({ timezoneId: 'America/Los_Angeles' });

for (const game of ['face-game', 'history-quiz']) test(`${game} solo stops at the configured question count`, async ({ guests }, info) => {
  const page = guests[0]!;
  const otherGame = game === 'face-game' ? 'history-quiz' : 'face-game';
  await page.goto(`/${otherGame}/rooms`);
  await page.getByRole('textbox', { name: '昵称' }).fill('阿林');
  await page.goto(`/${game}`);
  const display = game === 'face-game' ? '&crop=1&grid=10x0.2' : '';
  await expect(page).toHaveURL(new URL(`/${game}?n=25&t=15${display}`, page.url()).href);
  await expect(page.getByRole('link', { name: '多人对战' })).toHaveAttribute('href', `/${game}/rooms?n=25&t=15${display}&next=10&join=1`);
  await expect(page.getByRole('textbox', { name: '昵称' })).toHaveValue('阿林');
  let boardRequests = 0;
  page.on('request', request => { if (request.url().endsWith('/boards/current')) boardRequests++; });
  await expect(page.getByRole('radio', { name: '固定局数' })).toBeChecked();
  const count = page.getByLabel('题数', { exact: true });
  await count.fill('2'); await count.press('Tab');
  await expect(page).toHaveURL(new URL(`/${game}?n=2&t=15${display}`, page.url()).href);
  if (game === 'face-game') {
    await page.getByText('直接显示', { exact: true }).click();
    await expect(page).toHaveURL(new URL('/face-game?n=2&t=15&crop=1&grid=off', page.url()).href);
  }
  await page.getByRole('button', { name: '开始游戏' }).click();
  for (const number of [1, 2]) {
    await page.getByRole('button', { name: game === 'face-game' ? '都不是' : '提交日期', exact: true }).click();
    await expect(page.getByRole('heading', { name: `第 ${number}/2 题 · 答案揭晓` })).toBeVisible();
    await page.getByRole('button', { name: number === 1 ? '下一题' : '查看结果', exact: true }).click();
  }
  const preview = page.getByRole('region', { name: '榜单前五' });
  await expect(preview).toHaveCount(0);
  const name = page.getByText('上榜昵称').locator('input');
  await expect(name).toHaveValue('阿林');
  await name.fill('小林');
  await page.route('**/matches/*/score', route => route.fulfill({ status: 503, json: { detail: '提交失败，请重试' } }), { times: 1 });
  await page.getByRole('button', { name: '上传个人成绩' }).click();
  await expect(page.getByText('提交失败，请重试')).toBeVisible();
  await expect(preview).toHaveCount(0);
  expect(boardRequests).toBe(0);
  await page.getByRole('button', { name: '上传个人成绩' }).click();
  await expect(page.getByRole('button', { name: '成绩已提交' })).toBeDisabled();
  await expect(preview.getByRole('row', { name: /小林/ })).toBeVisible();
  await page.reload();
  await expect(preview.getByRole('row', { name: /小林/ })).toBeVisible();
  await page.screenshot({ path: info.outputPath('submitted.png'), fullPage: true });
  const nextTab = await page.context().newPage();
  await nextTab.goto(`/${otherGame}/rooms`);
  await expect(nextTab.getByRole('textbox', { name: '昵称' })).toHaveValue('小林');
  await nextTab.close();
  await page.getByRole('link', { name: '当前榜单', exact: true }).click();
  await expect(page.getByRole('row', { name: /小林/ })).toBeVisible();
  const time = page.locator('time');
  await expect(time).toHaveText(await time.evaluate(element => {
    const local = new Date(element.dateTime), pad = (value: number) => String(value).padStart(2, '0');
    return `${local.getFullYear()}/${pad(local.getMonth() + 1)}/${pad(local.getDate())} ${pad(local.getHours())}:${pad(local.getMinutes())}:${pad(local.getSeconds())}`;
  }));
  await page.screenshot({ path: info.outputPath('record-time.png') });
  await page.getByRole('link', { name: '按此规则开局' }).click();
  await expect(page.getByLabel('题数', { exact: true })).toHaveValue('2');
  if (game === 'face-game') await expect(page.getByRole('radio', { name: '直接显示' })).toBeChecked();
  for (const name of ['当前筛选的榜单', '全部榜单']) {
    await page.getByRole('link', { name, exact: true }).click();
    await expect(page.getByText('1 人上榜')).toBeVisible();
    await page.getByRole('link', { name: '按此规则开局' }).click();
  }
  await page.getByRole('link', { name: '当前榜单', exact: true }).click();
  await expect(page.getByRole('row', { name: /小林/ })).toBeVisible();
});

test('board access follows the active rules and empty lists retain their filters', async ({ guests }) => {
  const page = guests[0]!;
  const current = page.getByRole('link', { name: '当前榜单', exact: true });
  await page.goto('/face-game/rooms?people=1');
  await expect(current).toBeDisabled();
  await expect(current).not.toHaveAttribute('href', /.+/);
  await page.getByRole('link', { name: '单人游戏' }).click();
  await expect(current).toBeEnabled();
  const count = page.getByLabel('题数', { exact: true });
  await count.fill('12'); await count.press('Tab');
  await page.getByText('无尽', { exact: true }).click();
  await expect(current).toBeDisabled();
  await page.getByText('一命模式', { exact: true }).click();
  await expect(page.getByRole('radio', { name: '一命模式' })).toBeChecked();
  await expect(count).toHaveCount(0);
  await expect(current).toBeEnabled();
  await page.getByText('固定局数', { exact: true }).click();
  await expect(count).toHaveValue('12');
  await expect(current).toBeEnabled();
  await page.getByRole('link', { name: '当前筛选的榜单' }).click();
  await expect(page.getByRole('region', { name: '出题筛选' })).toContainText('人1');
  await expect(page.getByText('暂无榜单')).toBeVisible();
  await page.goto('/history-quiz?n=0');
  await expect(page.getByRole('radiogroup', { name: '游戏局数' }).getByRole('radio')).toHaveCount(2);
  await expect(current).toBeDisabled();
  await page.getByRole('button', { name: '开始游戏' }).click();
  await page.getByRole('button', { name: '结束本局' }).click();
  await expect(page.getByRole('region', { name: '本局结果' })).toBeVisible();
  await expect(page.getByRole('region', { name: '公开成绩' })).toHaveCount(0);
  await expect(page.getByText('本局不参与公开排名')).toHaveCount(0);
});
