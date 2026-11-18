import { computed, ref } from "vue";
import { useLibrary } from "./store";

export type PublisherAccount = { platform: string; username: string };
export function uniqueAccounts(accounts: PublisherAccount[]) {
  const unique = new Map<string, PublisherAccount>();
  for (const account of accounts) {
    const username = account.username.trim().replace(/^@+/, "").toLowerCase();
    if (username) unique.set(`${account.platform}:${username}`, { ...account, username });
  }
  return [...unique.values()];
}
export function accountUrl(account: PublisherAccount) {
  return `https://${account.platform === "x" ? "x.com" : "instagram.com"}/${account.username}`;
}
export function usePublisherSelection() {
  const store = useLibrary();
  const selected = ref<string[]>([]);
  const accounts = computed(() => uniqueAccounts(store.people
    .filter(person => selected.value.includes(`person:${person.id}`))
    .flatMap(person => person.accounts)));
  return { selected, accounts };
}

export function mergeImportUrls(accounts: PublisherAccount[], input: string) {
  return [...new Set([...accounts.map(accountUrl), ...input.split("\n").map(value => {
    const trimmed = value.trim();
    try {
      const url = new URL(trimmed);
      const username = url.pathname.replace(/^\/|\/$/g, "");
      const host = url.hostname.toLowerCase().replace(/^www\./, "");
      if (["http:", "https:"].includes(url.protocol) && ["x.com", "twitter.com", "instagram.com"].includes(host) && /^[a-zA-Z0-9_.]+$/.test(username))
        return accountUrl({ platform: host === "instagram.com" ? "instagram" : "x", username: username.toLowerCase() });
    } catch { /* The import endpoint reports invalid links individually. */ }
    return trimmed;
  }).filter(Boolean)])];
}
