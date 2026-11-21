import { test, expect } from '@playwright/test';
for (const width of [320, 390, 768, 1280, 1440]) {
  test(`Japanese embed-only browsing ${width}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    page.on('request', req => requests.push(req.url()));
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const body = path.endsWith('/site') ? { site_title: 'Gallery Faces' } : path.endsWith('/people') ? [1, 2].map(id => ({ id, name: '中文人物', name_ja: `日本語の名前 ${id}`, groups: [{id:1,name:'中文组'}], accounts:[], reference_count:1, avatar_reference_id:42 })) : path.endsWith('/groups') ? [{id:1,name:'中文组',name_ja:'グループ'}] : { items: [{ id:1,key:'x:20',platform:'x',url:'https://x.com/jack/status/20',embed_id:'20',author:'jack',author_name:null,published_at:'2026-01-01T00:00:00Z' }, {id:2,key:'instagram:abc',platform:'instagram',url:'https://www.instagram.com/p/abc/',embed_id:'abc',author:'test',author_name:null,published_at:'2026-01-01T00:00:00Z'}],next_cursor:null };
      await route.fulfill({ json: body });
    });
    await page.route('https://platform.twitter.com/widgets.js', route => route.fulfill({contentType:'application/javascript',body:`window.twttr={widgets:{createTweet:async(id,host)=>{ const f=document.createElement('iframe'); f.title='X 投稿'; f.src='https://platform.twitter.com/embed-test'; f.style='width:550px;max-width:100%;height:240px;border:0'; host.append(f); return f; }}};`}));
    await page.route('https://www.instagram.com/embed.js', route => route.fulfill({contentType:'application/javascript',body:`window.instgrm={Embeds:{process:()=>{document.querySelectorAll('blockquote.instagram-media').forEach(b=>{ const f=document.createElement('iframe');f.title='Instagram 投稿';f.src='https://www.instagram.com/embed-test'; f.className='instagram-media';f.style='width:540px;min-width:326px;max-width:540px;height:240px;margin:1px 1px 12px;border:0'; b.replaceWith(f); });}}};`}));
    await page.route('**/embed-test', route => route.fulfill({contentType:'text/html',body:'<html lang="ja"><head><meta charset="UTF-8"></head><body><p>テスト用の埋め込み投稿</p></body></html>'}));
    await page.goto('/admin/import?people=1,2&start=2026-01-01T00:00:00Z');
    await expect(page.getByRole('heading', {name:'投稿一覧'})).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang','ja');
    await expect(page.locator('footer')).toHaveCount(0);
    await expect(page.locator('a[href^="/admin"]')).toHaveCount(0);
    await expect(page.locator('iframe[title="X 投稿"]')).toBeVisible();
    await expect(page.locator('iframe[title="Instagram 投稿"]')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    const heading = await page.getByRole('heading', {name:'投稿一覧'}).boundingBox();
    const timeline = await page.locator('.post-timeline').boundingBox();
    expect(heading!.x).toBe(timeline!.x);
    for (const title of ['X 投稿', 'Instagram 投稿']) {
      const embed = await page.locator(`iframe[title="${title}"]`).boundingBox();
      expect(embed!.x).toBe(timeline!.x);
      expect(embed!.width).toBe(timeline!.width);
    }
    if (width <= 900) await page.getByRole('button',{name:'絞り込み',exact:true}).click();
    const filters = page.locator('.filters:visible');
    const modes = filters.getByRole('radiogroup', {name:'人物の絞り込み条件'});
    const buttons = modes.locator('.n-radio-button');
    await expect(buttons).toHaveText(['いずれか', '全員', '選んだ人だけ']);
    expect(await buttons.evaluateAll(elements => new Set(elements.map(el => el.getBoundingClientRect().top)).size)).toBe(1);
    expect(await filters.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const dates = filters.getByLabel('開始日時', {exact:true});
    await expect(dates).not.toHaveValue('');
    const label = await filters.locator('.date-field').first().boundingBox();
    const date = await dates.boundingBox();
    expect(date!.x).toBeGreaterThanOrEqual(label!.x + 28);
    await modes.getByText('選んだ人だけ', {exact:true}).click();
    await expect(modes.getByRole('radio', {name:'選んだ人だけ'})).toBeChecked();
    await page.locator('.people-cascader:visible .n-base-selection').last().click();
    await expect(page.getByText('グループ',{exact:true}).last()).toBeVisible();
    await page.locator('.people-cascader:visible .n-base-selection').last().click();
    if (width <= 900) await page.getByRole('button',{name:'絞り込みを適用',exact:true}).click();
    await expect(page).toHaveURL(/match=exact/);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.screenshot({path:`/tmp/gallery-faces/ja-${width}.png`,fullPage:true});
    await page.getByLabel('テーマ', { exact: true }).click();
    await page.getByText('ダーク', { exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('iframe[title="X 投稿"]')).toHaveCSS('color-scheme', 'light');
    await page.screenshot({path:`/tmp/gallery-faces/ja-${width}-dark.png`,fullPage:true});
    expect(requests.filter(url => /\/api\/v1\/(media|gallery|admin|session)/.test(url))).toEqual([]);
    await expect(page.locator('img')).toHaveCount(0);
  });
}
test('embed failure never falls back to images', async ({page}) => {
  await page.route('**/api/v1/**', route => route.fulfill({json: route.request().url().includes('/posts') ? {items:[{id:1,key:'x:20',platform:'x',url:'https://x.com/jack/status/20',embed_id:'20',author:'jack',published_at:'2026-01-01T00:00:00Z'}], next_cursor:null} : route.request().url().includes('/site') ? {site_title:'Gallery Faces'} : []}));
  await page.route('https://platform.twitter.com/widgets.js', route => route.abort());
  await page.goto('/');
  await expect(page.getByText('投稿を表示できません。')).toBeVisible();
  await expect(page.getByRole('link',{name:'Xで投稿を見る'})).toBeVisible();
  await page.getByRole('button',{name:'再試行',exact:true}).click();
  await expect(page.getByText('投稿を表示できません。')).toBeVisible();
  await expect(page.locator('img')).toHaveCount(0);
});

test('CSP permits the inline favicon and blocks URL images', async ({page}) => {
  await page.route('**/api/v1/**', route => route.fulfill({json: route.request().url().includes('/posts') ? {items:[],next_cursor:null} : route.request().url().includes('/site') ? {site_title:'Gallery Faces'} : []}));
  await page.goto('/');
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', /^data:image\/svg\+xml,/);
  const result = await page.evaluate(async () => {
    const violations: string[] = [];
    document.addEventListener('securitypolicyviolation', event => {
      if (event.effectiveDirective === 'img-src') violations.push(event.blockedURI);
    });
    const loadImage = (src: string) => new Promise<boolean>(resolve => {
      const image = new Image();
      image.onload = () => resolve(true);
      image.onerror = () => resolve(false);
      image.src = src;
    });
    const favicon = await loadImage(document.querySelector<HTMLLinkElement>('link[rel="icon"]')!.href);
    const local = await loadImage('/csp-test.svg');
    const external = await loadImage('https://example.com/csp-test.svg');
    return {favicon, local, external, violations};
  });
  expect(result.favicon).toBe(true);
  expect(result.local).toBe(false);
  expect(result.external).toBe(false);
  expect(result.violations).toEqual(expect.arrayContaining([
    expect.stringContaining('/csp-test.svg'), 'https://example.com/csp-test.svg',
  ]));
});
