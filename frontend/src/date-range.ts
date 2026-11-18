export function validInstant(value: string) {
  return /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}
export function utcOffset(seconds: number) {
  const absolute = Math.abs(seconds);
  const hours = Math.floor(absolute / 3600);
  const minutes = Math.floor(absolute % 3600 / 60);
  return `UTC${seconds < 0 ? "-" : "+"}${hours}` + (minutes ? `:${String(minutes).padStart(2, "0")}` : "");
}
export function rangeError(start: string, end: string) {
  if ([start, end].some(value => value && !validInstant(value))) return "旧日期链接或时间格式无效，请重新选择日期时间";
  if (start && end && Date.parse(end) <= Date.parse(start)) return "结束时间必须晚于开始时间";
  return "";
}
export function localRangeLabel(start: string, end: string) {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const offset = (value: string) => utcOffset(-new Date(value || Date.now()).getTimezoneOffset() * 60);
  return rangeError(start, end) || `${zone} · 包含开始，不含结束 · 开始 ${offset(start)} / 结束 ${offset(end)}`;
}
