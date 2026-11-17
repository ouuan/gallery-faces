import { defineStore } from "pinia";
import { ref, computed } from "vue";
import {
  api,
  setSiteTimezone,
  publisherLabel,
  type Person,
  type Source,
} from "./api";
export const useLibrary = defineStore("library", () => {
  const people = ref<Person[]>([]),
    groups = ref<{ id: number; name: string }[]>([]),
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
  async function loadSite() {
    const site = await api("/site");
    setSiteTimezone(site.timezone || "Asia/Shanghai");
    siteTitle.value = site.site_title || "Gallery Faces";
  }
  async function load() {
    const [persons, collections] = await Promise.all([
      api("/people"),
      api("/groups"),
      loadSite(),
    ]);
    people.value = persons;
    groups.value = collections;
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
    siteTitle,
    theme,
    dark,
    load,
    loadSite,
    setTheme,
    publisherName,
  };
});
