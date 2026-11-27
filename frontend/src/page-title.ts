import { ref, toValue, watchEffect, type MaybeRefOrGetter } from "vue";
import { useLibrary } from "./store";

export const currentPageTitle = ref('');

export function usePageTitle(title: MaybeRefOrGetter<string>) {
  const store = useLibrary();
  watchEffect(() => {
    const value = toValue(title);
    currentPageTitle.value = value;
    document.title = `${store.siteTitle} · ${value}`;
  });
}
