import { expect, test } from '@playwright/test';

for (const width of [375, 1280]) test(`filtered face game, shared feedback and scoring at ${width}px`, async ({ page }, testInfo) => {
  const admin = width === 1280;
  await page.setViewportSize({ width, height: admin ? 860 : 667 });
  const face = { id: 19, box: [80, 40, 160, 120], revision: 2, person_id: 1, locked: true };
  const choices = [{ id: 1, name: '甲' }, { id: 2, name: '乙' }, { id: 3, name: '一位名字很长的候选人物' }, { id: 4, name: 'Alex Chen' }];
  const question = { group_id: 9, image_id: 15, width: 800, height: 400, image_url: '/fixture.jpg', choices, face };
  const source = { id: 33, key: 'x:33', platform: 'x', author: 'fixture', published_at: '2026-01-01', url: 'https://x.com/fixture/status/33' };
  const photo = { ...question, id: 9, people: choices, source_count: 1, sources: [source], matched_source: source,
    faces: [face, { ...face, id: 20, box: [320, 40, 160, 120] }] };
  let draws = 0, details = 0, galleryLoads = 0, failFeedback = true;
  let resumeSecondDraw!: () => void;
  const secondDraw = new Promise<void>(resolve => { resumeSecondDraw = resolve; });
  const sent: Record<string, unknown>[] = [];
  let releasePhoto!: () => void;
  const photoPending = new Promise<void>(resolve => { releasePhoto = resolve; });
  await page.route('**/fixture.jpg', async route => {
    await photoPending;
    await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400"><rect width="800" height="400" fill="#b8bcc1"/><rect x="80" y="40" width="160" height="120" fill="#64869e"/><rect x="320" y="40" width="160" height="120" fill="#bc9469"/></svg>' });
  });
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.endsWith('/face-game')) {
      expect(url.searchParams.get('people')).toBe('1,2');
      if (draws++) { expect(url.searchParams.get('last_face')).toBe('19'); expect(url.searchParams.get('last_group')).toBe('9'); }
      if (draws === 2) await secondDraw;
      if (draws >= 4) return route.fulfill({ json: { ...question, choices: [...choices.slice(1), { id: 5, name: '丙' }] } });
      return route.fulfill({ json: question });
    }
    if (path.endsWith('/gallery/9')) {
      if (!details++) return route.fulfill({ status: 503, json: { detail: '暂时无法读取来源' } });
      return route.fulfill({ json: photo });
    }
    if (path.endsWith('/people')) return route.fulfill({ json: choices.map(person => ({ ...person, groups: [], accounts: [] })) });
    if (path.endsWith('/gallery')) { galleryLoads++; return route.fulfill({ json: { items: [], total: 0, next_cursor: null } }); }
    if (path.endsWith('/session')) return route.fulfill({ json: { admin } });
    if (path.endsWith('/posts/x%3A33')) return route.fulfill({ status: 404, json: { detail: '帖子不存在' } });
    if (path.endsWith('/feedback')) {
      if (failFeedback) { failFeedback = false; return route.fulfill({ status: 503, json: { detail: '请重试反馈' } }); }
      sent.push(route.request().postDataJSON());
      return route.fulfill({ status: 201, json: { id: sent.length } });
    }
    return route.fulfill({ json: path.endsWith('/site') ? {} : [] });
  });
  await page.goto('/?people=1,2&sort=oldest');
  if (!admin) await page.getByRole('button', { name: '筛选', exact: true }).click();
  await page.getByRole('link', { name: '认脸游戏' }).click();
  await expect(page).toHaveURL(/face-game\?people=1(?:,|%2C)2$/);
  const button = (name: string) => page.getByRole('button', { name, exact: true });
  const options = page.getByRole('group', { name: '框中的是谁？' });
  const photoFrame = page.locator('.game-frame');
  const picture = page.locator('.game-picture');
  const layout = () => Promise.all([photoFrame.boundingBox(), options.boundingBox()]);
  await expect(options).toBeVisible();
  const loadingLayout = await layout();
  releasePhoto();
  await expect(button('甲')).toBeEnabled();
  expect(await layout()).toEqual(loadingLayout);
  const pictureHeight = (await picture.boundingBox())!.height;
  expect(pictureHeight).toBeGreaterThan(0);
  const optionBoxes = () => options.evaluate(group => {
    const origin = group.getBoundingClientRect();
    return Array.from(group.querySelectorAll('button'), button => {
      const { x, y, width, height } = button.getBoundingClientRect();
      return { x: x - origin.x, y: y - origin.y, width, height };
    });
  });
  const initialBoxes = await optionBoxes();
  await expect(button('都不是')).toBeInViewport({ ratio: 1 });
  const [first, second, third, fourth, fallback] = initialBoxes;
  expect(first.y).toBe(second.y);
  expect(third.y).toBe(fourth.y);
  expect(first.x).toBe(third.x);
  expect(fallback.width).toBeCloseTo(second.x + second.width - first.x, 1);
  expect(fallback.y).toBeGreaterThan(third.y);
  expect(initialBoxes.every(box => box.height >= 44)).toBe(true);
  await testInfo.attach('答题选项', { body: await options.screenshot(), contentType: 'image/png' });
  expect(details).toBe(0);
  const frame = (await page.getByAltText('题目照片').boundingBox())!;
  const box = (await page.locator('.target-face').boundingBox())!;
  expect(Math.abs(box.x - frame.x - frame.width * .1)).toBeLessThan(1);
  expect(Math.abs(box.height - frame.height * .3)).toBeLessThan(1);
  const zoomButton = button('按住放大人脸');
  await zoomButton.hover();
  await page.mouse.down();
  await expect(page.locator('.target-face')).toBeHidden();
  const zoomed = (await page.getByAltText('题目照片').boundingBox())!;
  expect(zoomed.height / frame.height).toBeCloseTo(5 / 3);
  await page.mouse.move(0, 0);
  await page.mouse.up();
  await expect(page.locator('.target-face')).toBeVisible();
  expect(await page.getByAltText('题目照片').boundingBox()).toEqual(frame);
  await zoomButton.focus();
  for (const key of ['Space', 'Enter']) {
    await page.keyboard.down(key);
    await expect(page.locator('.target-face')).toBeHidden();
    await page.keyboard.up(key);
    await expect(page.locator('.target-face')).toBeVisible();
  }
  await button('甲').click();
  await expect(button('下一题')).toBeEnabled();
  await expect(button('下一题')).toBeInViewport({ ratio: 1 });
  const result = page.getByRole('status').filter({ hasText: /图库答案|本题已记为存疑/ });
  await expect(result).toHaveText('答对了。图库答案：甲');
  await expect(result).toHaveCSS('clip-path', 'inset(50%)');
  expect(await optionBoxes()).toEqual(initialBoxes);
  await button('重试加载详情').click();
  await expect(page.getByRole('region', { name: '图片来源' })).toBeVisible();
  const sidebarHeadings = page.locator('.detail-sidebar').getByRole('heading');
  const peopleTitle = choices.map(person => person.name).join('、');
  await expect(sidebarHeadings.first()).toHaveText(peopleTitle);
  await expect(sidebarHeadings.last()).toHaveText('图片反馈');
  await expect(page.getByRole('link', { name: '管理此图片', exact: true })).toHaveCount(admin ? 1 : 0);
  await expect(page.getByRole('link', { name: '在图库中查看' })).toHaveCount(0);
  await expect(button('选择人脸')).toBeVisible();
  await button('下一题').click();
  try {
    await expect(page.getByText('正在出题…', { exact: true })).toBeVisible();
    await expect(options).toHaveCount(0);
    expect((await picture.boundingBox())?.height).toBe(pictureHeight);
  } finally { resumeSecondDraw(); }
  await expect(page.locator('.target-face')).toBeVisible();
  await button('乙').click();
  await expect(result).toHaveText('答错了，你选了乙。图库答案：甲');
  await expect(page.getByLabel('建议人物')).toContainText('乙');
  await expect(sidebarHeadings.first()).toHaveText('图片反馈');
  await expect(sidebarHeadings.nth(1)).toHaveText(peopleTitle);
  await expect(sidebarHeadings.nth(2)).toHaveText('来源 · 1');
  await expect(page.getByText('这张人脸已经人工确认，你仍可提交反馈。')).toBeVisible();
  const firstPreview = button('更换人脸 #1').locator('svg');
  await expect(firstPreview).toHaveAttribute('viewBox', '80 40 160 120');
  const firstCrop = await firstPreview.screenshot();
  await testInfo.attach('答题结果', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  await button('更换人脸 #1').click();
  await button('选择人脸 #2').click();
  const secondPreview = button('更换人脸 #2').locator('svg');
  await expect(secondPreview).toHaveAttribute('viewBox', '320 40 160 120');
  expect(await secondPreview.screenshot()).not.toEqual(firstCrop);
  await button('提交反馈').click();
  await expect(page.getByText('请重试反馈')).toBeVisible();
  await button('提交反馈').click();
  await expect(page.getByText('错误 1', { exact: true })).toBeVisible();
  await expect(result).not.toHaveText('本题已记为存疑');
  await expect(button('选择人脸')).toBeVisible();
  await expect(button('选择人脸').locator('svg')).toHaveCount(0);
  await button('选择人脸').click();
  await button('选择人脸 #1').click();
  await page.getByRole('checkbox', { name: '不是人脸' }).check();
  await button('提交反馈').click();
  await expect(page.getByText('存疑 1', { exact: true })).toBeVisible();
  await expect(result).toHaveText('本题已记为存疑');
  await expect(sidebarHeadings.first()).toContainText('图片反馈');
  await expect(result).toHaveCSS('clip-path', 'none');
  await expect(page.getByText('正确率 100%')).toBeVisible();
  await expect(page.getByText('连对 1')).toBeVisible();
  expect(sent).toEqual([{ content: '', face_id: 20, face_revision: 2, suggested_person_id: null, not_face: false },
    { content: '', face_id: 19, face_revision: 2, suggested_person_id: null, not_face: true }]);
  await button('下一题').click();
  await button('都不是').click();
  await expect(button('更换人脸 #1')).toBeVisible();
  await expect(page.getByLabel('建议人物')).toContainText('建议人物（可不选）');
  const gameUrl = page.url(), requests = { galleryLoads, details, draws };
  const draft = page.getByRole('textbox', { name: '反馈内容' });
  await draft.fill('还没提交的说明');
  const sourceLink = page.getByRole('link', { name: 'X · fixture' });
  await sourceLink.click();
  await expect(page).toHaveURL(/\/face-game\?.*post=x(?::|%3A)33/);
  await expect(page.getByRole('dialog', { name: '帖子详情' })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(gameUrl);
  await page.goForward();
  await button('关闭帖子详情').click();
  await expect(page).toHaveURL(gameUrl);
  await expect(page).toHaveTitle(/认脸游戏$/);
  await expect(draft).toHaveValue('还没提交的说明');
  await expect(button('更换人脸 #1')).toBeVisible();
  expect({ galleryLoads, details, draws }).toEqual(requests);
  expect(draws).toBe(3);
  await button('下一题').click();
  await expect(button('甲')).toHaveCount(0);
  await button('都不是').click();
  await expect(result).toHaveText('答对了。图库答案：甲');
  await expect(button('都不是（甲）')).toHaveClass(/right/);
  await button('下一题').click();
  await button('丙').click();
  await expect(result).toHaveText('答错了，你选了丙。图库答案：甲');
  await expect(button('都不是（甲）')).toHaveClass(/right/);
  await expect(button('丙')).toHaveClass(/wrong/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
