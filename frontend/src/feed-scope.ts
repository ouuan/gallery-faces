export const feedPlatforms = ['x', 'instagram'];
export const defaultScope = { retweets: false, quoted: false, stories: true, tagged: true, reposts: false };
export type FeedScope = typeof defaultScope;

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
