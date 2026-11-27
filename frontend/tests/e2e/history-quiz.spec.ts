import { expect } from '@playwright/test';
import { test } from '../room-fixture';

test('history quiz keeps the selected filters and score across mobile navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let rounds = 0, details = 0;
  await page.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/gallery/history-quiz')) {
      expect(url.searchParams.get('people')).toBe('1-2');
      expect(url.searchParams.get('include_no_faces')).toBe('true');
      return route.fulfill({ json: { group_id: ++rounds, image_id: 9, first_date: '2026-01-01', last_date: '2026-01-10',
        correct_date: '2026-01-08', width: 160, height: 100, image_url: '/quiz-fixture.svg' } });
    }
    if (/\/gallery\/\d+$/.test(url.pathname)) {
      details++;
      return route.fulfill({ json: { image_id: 9, source_count: 0, sources: [] } });
    }
    return route.fulfill({ json: url.pathname.endsWith('/gallery') ? { items: [], total: 0, next_cursor: null } : [] });
  });
  await page.route('**/quiz-fixture.svg', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="100"><rect width="160" height="100" fill="#ddd"/><text x="48" y="54">布局示例</text></svg>' }));
  await page.goto('/?people=1,2&sort=oldest');
  await page.getByRole('button', { name: '图库菜单：Gallery Faces' }).click();
  await page.getByRole('link', { name: '史官测验' }).click();
  await expect(page).toHaveURL(/history-quiz\?people=1-2$/);
  const slider = page.getByRole('slider', { name: '猜测日期' });
  await expect(slider).toHaveCount(0);
  expect(rounds).toBe(0);
  const filterToggle = page.getByRole('button', { name: /筛选照片/ });
  await expect(filterToggle).toContainText('2 位人物');
  await filterToggle.click();
  await page.getByRole('checkbox', { name: '包含无人脸图片' }).check();
  await page.getByRole('button', { name: '开始游戏' }).click();
  await expect(slider).toHaveAttribute('aria-valuetext', '2026-01-05');
  await expect(page.getByRole('button', { name: '提交日期' })).toBeEnabled();
  await expect(page.getByRole('dialog', { name: '图库菜单' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '图库菜单：史官测验' })).toHaveText('史官测验');
  expect(details).toBe(0);
  await slider.press('ArrowRight');
  const picker = page.getByRole('textbox', { name: '选择猜测日期' });
  await expect(picker).toHaveValue('2026-01-06');
  await picker.click();
  const calendar = page.locator('.n-date-panel-dates');
  await expect(calendar.getByText('11', { exact: true })).toHaveClass(/--disabled/);
  await calendar.locator('.n-date-panel-date:not(.n-date-panel-date--excluded)').getByText('7', { exact: true }).click();
  await expect(slider).toHaveAttribute('aria-valuetext', '2026-01-07');
  await page.getByRole('button', { name: '前一天' }).click();
  await expect(picker).toHaveValue('2026-01-06');
  await page.getByRole('button', { name: '提交日期' }).click();
  await expect(page.getByText('你的猜测：2026-01-06 · 早了 2 天')).toBeVisible();
  await expect(slider).toBeDisabled();
  await page.getByRole('button', { name: '下一题' }).click();
  await page.getByRole('button', { name: '前一天' }).click();
  await page.getByRole('button', { name: '提交日期' }).click();
  await expect(page.getByText('平均偏差 3.0 天')).toBeVisible();
  await page.getByRole('link', { name: '返回图库' }).click();
  await page.goBack();
  await expect(page.getByText('平均偏差 3.0 天')).toBeVisible();
  const summary = page.getByRole('region', { name: '本局结果' });
  await page.getByRole('button', { name: '结束本局' }).click();
  await expect(summary.getByText('3.0', { exact: true })).toBeVisible();
  const breakdown = summary.getByRole('region', { name: '作答分布' });
  await expect(breakdown.getByRole('term')).toHaveText(['猜早', '正好', '猜晚']);
  await expect(breakdown.getByRole('definition')).toHaveText(['2 题', '0 题', '0 题']);
  await expect(summary.getByRole('region', { name: '出题筛选' })).toContainText('包含无人脸图片');
  await expect(summary).toContainText('已答 2 题');
  await expect(summary).toContainText('累计偏差 6 天');
  await page.reload();
  await page.getByRole('button', { name: '开始游戏' }).click();
  await expect(page.getByText('已答 0 题')).toBeVisible();
  await page.getByRole('button', { name: '结束本局' }).click();
  await expect(summary).toContainText('已答 0 题');
  await expect(summary.getByText('—', { exact: true })).toBeVisible();
  await expect(summary).toContainText('本局尚未提交答案');
  await expect(page.getByRole('form', { name: '开局设置' })).toHaveCount(0);
  await summary.getByRole('button', { name: '再来一局' }).click();
  await expect(summary).toHaveCount(0);
  await filterToggle.click();
  await expect(page.getByRole('checkbox', { name: '包含无人脸图片' })).toBeChecked();
});

test('history room splits a point between three closest guesses and preserves the result on reload', async ({ guests }) => {
  const [host, guest, late] = guests;
  await host.goto('/history-quiz/rooms');
  await expect(host.getByRole('switch', { name: '允许中途加入' })).toBeChecked();
  await host.getByRole('textbox', { name: '昵称' }).fill('甲');
  await host.getByRole('button', { name: /筛选照片/ }).click();
  await host.getByRole('checkbox', { name: '包含无人脸图片' }).check();
  const wait = host.locator('.n-input-number input').nth(1);
  await wait.fill('0'); await wait.press('Tab');
  await host.getByText('固定局数', { exact: true }).click();
  const count = host.getByLabel('题数', { exact: true });
  await count.fill('1'); await count.press('Tab');
  await host.getByRole('button', { name: '创建并进入' }).click();
  await expect(host.getByRole('heading', { name: /等待开局/ })).toBeVisible();
  const path = new URL(host.url()).pathname;
  for (const [player, name] of [[guest, '乙'], [late, '丙']] as const) {
    await player.goto(path);
    await expect(player.getByRole('region', { name: '对战规则' })).toContainText('共 1 题');
    await player.getByRole('textbox', { name: '昵称' }).fill(name);
    await player.getByRole('button', { name: '进入房间' }).click();
    await expect(player.getByRole('table')).toContainText(name);
    if (player === guest) {
      const summary = guest.getByRole('region', { name: '出题筛选' });
      await expect(summary).toContainText('包含无人脸图片');
      await host.getByRole('button', { name: '修改设置' }).click();
      await host.getByRole('button', { name: /筛选照片/ }).click();
      await host.getByRole('button', { name: '清空' }).click();
      await host.getByRole('button', { name: '保存设置' }).click();
      await expect(summary).toContainText('未设置筛选');
      await host.getByRole('button', { name: '开始对战' }).click();
    }
  }
  await expect(late.getByRole('button', { name: '提交日期' })).toBeEnabled();
  await expect(host.getByRole('slider')).toBeDisabled();
  await host.getByRole('button', { name: '提交日期' }).click();
  await expect(guest.getByText(/最早来源：/)).toHaveCount(0);
  await guest.getByRole('button', { name: '提交日期' }).click();
  await late.getByRole('button', { name: '提交日期' }).click();
  await expect(host.getByRole('table').getByRole('columnheader', { name: '本题猜测' })).toBeVisible();
  await late.reload();
  await expect(late.getByText('你和甲、乙并列最接近')).toBeVisible();
  await expect(late.getByRole('group', { name: '我的战绩' })).toContainText('已结算 1 题 · 未答 0');
  for (const player of [host, guest, late]) await player.getByRole('button', { name: '确认结算' }).click();
  await expect(guest.getByRole('heading', { name: '最终排名' })).toBeVisible();
  const finalRecord = late.getByRole('group', { name: '我的战绩' });
  await expect(finalRecord).toContainText('并列第 1 名');
  await expect(finalRecord).toContainText('0.33333 分');
  await expect(finalRecord).toContainText('已答 1 题');
  await expect(finalRecord).toContainText('未答 0 题');
  await expect(late.getByRole('table').getByRole('columnheader')).toHaveText(['名次', '玩家', '分数', '总偏差', '未答']);
  await expect(guest.getByRole('region', { name: '出题筛选' })).toContainText('未设置筛选');
});
