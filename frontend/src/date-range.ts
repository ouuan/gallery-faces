export function validInstant(value: string) {
  return /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}
export function rangeError(start: string, end: string) {
  if ([start, end].some(value => value && !validInstant(value))) return "旧日期链接或时间格式无效，请重新选择日期时间";
  if (start && end && Date.parse(end) <= Date.parse(start)) return "结束时间必须晚于开始时间";
  return "";
}
