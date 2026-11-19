import { test, expect } from '@playwright/test';
for (const width of [390, 1280]) {
  test(`Japanese embed-only browsing ${width}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width, height: 900 });
    const requests: string[] = [];
    page.on('request', req => requests.push(req.url()));
    await page.route('**/api/v1/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const body = path.endsWith('/site') ? { site_title: 'Gallery Faces' } : path.endsWith('/people') ? [{ id: 1, name: '中文人物', name_ja: '日本語の名前', groups: [{id:1,name:'中文组'}], accounts:[], reference_count:1, avatar_reference_id:42 }] : path.endsWith('/groups') ? [{id:1,name:'中文组',name_ja:'グループ'}] : { items: [{ id:1,key:'x:20',platform:'x',url:'https://x.com/jack/status/20',embed_id:'20',author:'jack',author_name:null,published_at:'2026-01-01T00:00:00Z' }, {id:2,key:'instagram:abc',platform:'instagram',url:'https://www.instagram.com/p/abc/',embed_id:'abc',author:'test',author_name:null,published_at:'2026-01-01T00:00:00Z'}],next_cursor:null };
      await route.fulfill({ json: body });
    });
    await page.route('https://platform.twitter.com/widgets.js', route => route.fulfill({contentType:'application/javascript',body:`window.twttr={widgets:{createTweet:async(id,host)=>{ const f=document.createElement('iframe'); f.title='X 投稿'; f.src='https://platform.twitter.com/embed-test'; host.append(f); return f; }}};`}));
    await page.route('https://www.instagram.com/embed.js', route => route.fulfill({contentType:'application/javascript',body:`window.instgrm={Embeds:{process:()=>{document.querySelectorAll('blockquote.instagram-media').forEach(b=>{ const f=document.createElement('iframe');f.title='Instagram 投稿';f.src='https://www.instagram.com/embed-test'; b.replaceWith(f); });}}};`}));
    await page.route('**/embed-test', route => route.fulfill({contentType:'text/html',body:'<html lang="ja"><head><meta charset="UTF-8"></head><body><p>テスト用の埋め込み投稿</p></body></html>'}));
    await page.goto('/admin/import');
    await expect(page.getByRole('heading', {name:'投稿一覧'})).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang','ja');
    await expect(page.locator('footer')).toHaveCount(0);
    await expect(page.locator('a[href^="/admin"]')).toHaveCount(0);
    await expect(page.locator('iframe[title="X 投稿"]')).toBeVisible();
    await expect(page.locator('iframe[title="Instagram 投稿"]')).toBeVisible();
    if (width === 390) await page.getByRole('button',{name:'絞り込み',exact:true}).click();
    await page.locator('.people-cascader:visible .n-base-selection').last().click();
    await expect(page.getByText('グループ',{exact:true}).last()).toBeVisible();
    await page.locator('.people-cascader:visible .n-base-selection').last().click();
    if (width === 390) await page.getByRole('button',{name:'適用',exact:true}).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.screenshot({path:`/tmp/gallery-faces/ja-${width}.png`,fullPage:true});
    await page.getByLabel('テーマ', { exact: true }).click();
    await page.getByText('ダーク', { exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
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
  await expect(page.getByRole('link',{name:'X で投稿を見る'})).toBeVisible();
  await page.getByRole('button',{name:'再試行',exact:true}).click();
  await expect(page.getByText('投稿を表示できません。')).toBeVisible();
  await expect(page.locator('img')).toHaveCount(0);
});
