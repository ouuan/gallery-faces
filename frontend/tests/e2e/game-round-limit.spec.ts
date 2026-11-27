import { expect } from '@playwright/test';
import { test } from '../room-fixture';

for (const game of ['face-game', 'history-quiz']) test(`${game} solo stops at the configured question count`, async ({ guests }) => {
  const page = guests[0]!;
  let draws = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === `/api/v1/gallery/${game}`) draws++; });
  await page.goto(`/${game}`);
  await expect(page.getByRole('radio', { name: '无尽' })).toBeChecked();
  await page.getByText('固定局数', { exact: true }).click();
  const count = page.getByLabel('题数', { exact: true });
  await count.fill('2'); await count.press('Tab');
  await page.getByRole('button', { name: '开始游戏' }).click();
  for (const number of [1, 2]) {
    await page.getByRole('button', { name: game === 'face-game' ? '都不是' : '提交日期', exact: true }).click();
    await expect(page.getByText(`已答 ${number}/2 题`)).toBeVisible();
    await page.getByRole('button', { name: number === 1 ? '下一题' : '查看结果' }).click();
  }
  await expect(page.getByRole('region', { name: '本局结果' })).toContainText('已答 2 题');
  expect(draws).toBe(2);
});
