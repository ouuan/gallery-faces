import { expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { dateLabel } from '../src/api';
import { activityTime, socialTime, useActivityClock } from '../src/social-time';

it('shows match activity in seconds, then minutes, then the full local timestamp', () => {
  const activity = '2026-12-31T23:45:00Z', start = Date.parse(activity);
  for (const [elapsed, label] of [[0, '0秒前'], [999, '0秒前'], [1000, '1秒前'], [59_999, '59秒前'], [60_000, '1分钟前'], [3_599_999, '59分钟前'],
    [3_600_000, dateLabel(activity)], [86_400_000, dateLabel(activity)]] as const) {
    expect(activityTime(activity, start + elapsed)).toBe(label);
  }
});

it('updates the activity label every second without reloading', async () => {
  const activity = '2026-12-31T23:45:00Z';
  vi.useFakeTimers();
  vi.setSystemTime(Date.parse(activity) + 58_000);
  const view = mount({ setup() {
    const now = useActivityClock();
    return () => activityTime(activity, now.value);
  } });
  try {
    for (const label of ['58秒前', '59秒前', '1分钟前']) {
      await view.vm.$nextTick();
      expect(view.text()).toBe(label);
      vi.advanceTimersByTime(1000);
    }
  } finally {
    view.unmount();
    vi.useRealTimers();
  }
});

it('uses elapsed time before the local year boundary and switches at exactly 24 hours', () => {
  const now = new Date(2027, 0, 1, 6).valueOf();
  for (const [minutes, label] of [[0, '刚刚'], [1, '1分钟前'], [59, '59分钟前'], [60, '1小时前'], [1439, '23小时前'], [1440, '2026年12月31日']] as const) {
    expect(socialTime(new Date(now - minutes * 60_000).toISOString(), now)).toBe(label);
  }
  expect(socialTime(new Date(now).toISOString(), new Date(2027, 1, 10).valueOf())).toBe('1月1日');
});
