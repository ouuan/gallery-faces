import { ref } from "vue";
export class ApiError extends Error {
  constructor(message: string, public status: number, public retryAfter: number) { super(message); }
}
export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      "X-Gallery-Request": "1",
      ...options.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof error.detail === "string"
        ? error.detail
        : `请求失败 (${response.status})`,
      response.status,
      Number(response.headers.get("Retry-After")) || 0,
    );
  }
  return response.json();
}
export const send = (path: string, body: unknown, method = "POST") =>
  api(path, { method, body: JSON.stringify(body) });
export type Person = {
  id: number;
  name: string;
  groups: { id: number; name: string }[];
  accounts: { platform: string; username: string }[];
  reference_count: number;
  avatar_reference_id: number | null;
};
export type Source = {
  id?: number;
  post_id?: number;
  platform: string;
  author: string;
  author_name?: string | null;
  published_at: string;
  url: string;
  post_text?: string | null;
};
export const platformLabel = (platform?: string) =>
  platform === "x"
    ? "X"
    : platform === "instagram"
      ? "Instagram"
      : platform || "";
export function publisherLabel(source: Source, people: Person[]) {
  const linked = people.filter((person) =>
    person.accounts.some(
      (account) =>
        account.platform === source.platform &&
        account.username.toLowerCase() === source.author?.toLowerCase(),
    ),
  );
  return (
    linked.map((person) => person.name).join("、") ||
    source.author_name?.trim() ||
    source.author ||
    "缺少发布者"
  );
}
export type DetailSource = Source & { images: { image_id: number; width: number; height: number }[] };
export type Photo = {
  id: number;
  image_id: number;
  width: number;
  height: number;
  people: { id: number; name: string }[];
  source_count: number;
  pending_feedback_count?: number;
  matched_source: Source;
  sources?: DetailSource[];
  earliest_source?: Source;
  members?: any[];
};
export const siteTimezone = ref("Asia/Shanghai");
export function setSiteTimezone(value: string) {
  siteTimezone.value = value;
}
export const dateLabel = (value: string | null | undefined) =>
  !value ? "缺少日期" :
  new Intl.DateTimeFormat("zh-CN", {
    timeZone: siteTimezone.value,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));

export type ImportResult = { value: string; status: "queued" | "duplicate" | "invalid"; task_id?: number };
