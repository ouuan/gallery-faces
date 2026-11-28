import { onMounted, onUnmounted, ref } from 'vue';
import { dateLabel } from './api';

const now = ref(Date.now());
let listeners = 0;
let timer: ReturnType<typeof setInterval>;

export function useClock() {
  onMounted(() => {
    if (++listeners === 1) {
      now.value = Date.now();
      timer = setInterval(() => { now.value = Date.now(); }, 15_000);
    }
  });
  onUnmounted(() => { if (--listeners === 0) clearInterval(timer); });
  return now;
}

export function activityTime(value: string, current: number) {
  const seconds = Math.floor((current - Date.parse(value)) / 1000);
  if (!Number.isFinite(seconds)) return '缺少日期';
  if (seconds < 0 || seconds >= 3600) return dateLabel(value);
  return seconds < 60 ? `${seconds}秒前` : `${Math.floor(seconds / 60)}分钟前`;
}

export function socialTime(value: string, current: number) {
  const date = new Date(value), minutes = Math.floor((current - date.valueOf()) / 60000);
  if (!Number.isFinite(minutes)) return '缺少日期';
  if (minutes >= 0 && minutes < 1440) {
    if (!minutes) return '刚刚';
    return minutes < 60 ? `${minutes}分钟前` : `${Math.floor(minutes / 60)}小时前`;
  }
  const year = date.getFullYear();
  return `${year === new Date(current).getFullYear() ? '' : year + '年'}${date.getMonth() + 1}月${date.getDate()}日`;
}
