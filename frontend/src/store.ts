import { ja } from "./locale";
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import {
  api,
  publisherLabel,
  type Person,
  type Source,
} from "./api";
export type PublisherCandidate = {
  platform: string;
  username: string;
  label: string;
};
export const useLibrary = defineStore("library", () => {
  const people = ref<Person[]>([]),
    groups = ref<{ id: number; name: string; name_ja?: string | null }[]>([]),
    publisherCandidates = ref<PublisherCandidate[]>([]),
    siteTitle = ref("Gallery Faces"),
    theme = ref(localStorage.getItem("theme") || "system"),
    systemDark = ref(matchMedia("(prefers-color-scheme: dark)").matches);
  matchMedia("(prefers-color-scheme: dark)").addEventListener(
    "change",
    (e) => (systemDark.value = e.matches),
  );
  const dark = computed(
    () =>
      theme.value === "dark" || (theme.value === "system" && systemDark.value),
  );
  let siteLoaded = false;
  let siteRequest: Promise<void> | null = null;
  let libraryRequest: Promise<void> | null = null;
  async function loadSite(force = false): Promise<void> {
    if (force && siteRequest) await siteRequest;
    if (siteRequest) return siteRequest;
    if (siteLoaded && !force) return;
    siteRequest = (async () => {
      const site = await api("/site");
      siteTitle.value = site.site_title || "Gallery Faces";
      siteLoaded = true;
    })();
    try { await siteRequest; } finally { siteRequest = null; }
  }
  async function load(): Promise<void> {
    if (libraryRequest) return libraryRequest;
    libraryRequest = (async () => {
      const [persons, collections, candidates] = await Promise.all([
        api("/people"),
        api("/groups"),
        api<PublisherCandidate[]>("/publisher-candidates"),
      ]);
      people.value = persons.map((p: Person) => ({ ...p, name: ja ? p.name_ja || p.name : p.name }));
      groups.value = collections.map((g: { name: string; name_ja?: string | null }) => ({ ...g, name: ja ? g.name_ja || g.name : g.name }));
      publisherCandidates.value = Array.isArray(candidates) ? candidates : [];
    })();
    try { await libraryRequest; } finally { libraryRequest = null; }
  }
  function setTheme(value: string) {
    theme.value = value;
    localStorage.setItem("theme", value);
  }
  function publisherName(source: Source) {
    return publisherLabel(source, people.value);
  }
  return {
    people,
    groups,
    publisherCandidates,
    siteTitle,
    theme,
    dark,
    load,
    loadSite,
    setTheme,
    publisherName,
  };
});
