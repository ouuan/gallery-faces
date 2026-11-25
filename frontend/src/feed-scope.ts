export const feedPlatforms = ['x', 'instagram'];
export const defaultScope = { retweets: false, quoted: false, stories: true, tagged: false, reposts: false };
export type FeedScope = typeof defaultScope;
export const scopeLabels = { retweets: '转推', quoted: '引用', stories: '快拍', tagged: 'tagged', reposts: '转发' } satisfies Record<keyof FeedScope, string>;

export function describeScope(scope?: Partial<FeedScope>) {
  const included: string[] = [], excluded: string[] = [];
  for (const key of Object.keys(scopeLabels) as (keyof FeedScope)[]) {
    if (scope?.[key] === true) included.push(scopeLabels[key]);
    if (scope?.[key] === false) excluded.push(scopeLabels[key]);
  }
  return [included.length ? `包含${included.join('、')}` : '', excluded.length ? `不含${excluded.join('、')}` : ''].filter(Boolean).join('，');
}

const reservedX = new Set(['i', 'home', 'search', 'explore', 'messages', 'settings', 'notifications', 'compose', 'intent', 'login', 'logout']);
const reservedInstagram = new Set(['accounts', 'direct', 'stories', 'explore', 'saved', 'share']);

export function supportsAccountScope(platform: string, username: string) {
  if (platform === 'x') return /^i\/lists\/\d+$/.test(username) || (/^[a-z\d_]{1,15}$/i.test(username) && !reservedX.has(username.toLowerCase()));
  return platform === 'instagram' && /^[a-z\d_.]{1,30}$/i.test(username) && !reservedInstagram.has(username.toLowerCase());
}

export function importScopePlatforms(urls: string[]) {
  const platforms = new Set<string>();
  for (const value of urls) {
    let url: URL;
    try { url = new URL(value); } catch { continue; }
    if (url.protocol !== 'https:' || url.username || url.password || url.port) continue;
    const host = url.hostname.replace(/^www\./, '');
    const platform = host === 'instagram.com' ? 'instagram' : ['x.com', 'twitter.com'].includes(host) ? 'x' : '';
    if (supportsAccountScope(platform, url.pathname.slice(1).replace(/\/+$/, ''))) platforms.add(platform);
  }
  return platforms;
}

export function monitorScope(platform: string, scope: FeedScope) {
  return platform === 'x' ? { retweets: scope.retweets, quoted: scope.quoted } : { stories: scope.stories, tagged: scope.tagged };
}
