import { api } from "./api";
import type { components } from "./schema";

export type DateBounds = components["schemas"]["DateBounds"];
const requests = new Map<string, Promise<DateBounds>>();

export function loadDateBounds(start: string, end: string, timezone: string) {
  const key = JSON.stringify([start, end, timezone]);
  let request = requests.get(key);
  if (!request) {
    request = api<DateBounds>("/date-bounds?" + new URLSearchParams({ start, end }))
      .finally(() => { requests.delete(key); });
    requests.set(key, request);
  }
  return request;
}

export function utcOffset(seconds: number) {
  const absolute = Math.abs(seconds);
  const hours = Math.floor(absolute / 3600);
  const minutes = Math.floor(absolute % 3600 / 60);
  const remainder = absolute % 60;
  return `UTC${seconds < 0 ? "-" : "+"}${hours}`
    + (minutes || remainder ? `:${String(minutes).padStart(2, "0")}` : "")
    + (remainder ? `:${String(remainder).padStart(2, "0")}` : "");
}

export function dateRangeLabel(bounds: DateBounds) {
  const { start, end } = bounds;
  if (!start && !end) return `当前按 ${utcOffset(bounds.current_offset_seconds)} 计算`;
  if (start && end && start.offset_seconds === end.offset_seconds)
    return `起止边界按 ${utcOffset(start.offset_seconds)} 计算，包含结束当天`;
  return [
    start && `开始：当日 00:00（${utcOffset(start.offset_seconds)}）`,
    end && `结束：次日 00:00（${utcOffset(end.offset_seconds)}），不含该时刻`,
  ].filter(Boolean).join("；");
}
