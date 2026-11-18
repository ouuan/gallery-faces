import { toValue, watchEffect, type MaybeRefOrGetter } from "vue";
import { useLibrary } from "./store";

export function usePageTitle(title: MaybeRefOrGetter<string>) {
  const store = useLibrary();
  watchEffect(() => {
    document.title = `${store.siteTitle} · ${toValue(title)}`;
  });
}
