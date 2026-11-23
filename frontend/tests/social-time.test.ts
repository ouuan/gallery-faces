import { expect, it } from 'vitest';
import { socialTime } from '../src/social-time';

it('uses elapsed time before the local year boundary and switches at exactly 24 hours', () => {
  const now = new Date(2027, 0, 1, 6).valueOf();
  for (const [minutes, label] of [[0, '刚刚'], [1, '1分钟前'], [59, '59分钟前'], [60, '1小时前'], [1439, '23小时前'], [1440, '2026年12月31日']] as const) {
    expect(socialTime(new Date(now - minutes * 60_000).toISOString(), now)).toBe(label);
  }
  expect(socialTime(new Date(now).toISOString(), new Date(2027, 1, 10).valueOf())).toBe('1月1日');
});
