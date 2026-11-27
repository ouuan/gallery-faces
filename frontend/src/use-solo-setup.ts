import { computed, ref, shallowRef, watch, type Ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { filterOnlyQuery, fromQuery, type Filter } from './filters';

export function useSoloSetup<Result>(activeScope: Ref<string | null>, reset: () => void, summarize: () => Result) {
  const route = useRoute(), router = useRouter();
  const page = route.path;
  const routeFilter = computed(() => fromQuery(route.query));
  const scope = computed(() => new URLSearchParams(filterOnlyQuery(routeFilter.value)).toString());
  const draft = ref(routeFilter.value);
  const query = computed(() => filterOnlyQuery(draft.value));
  const playing = computed(() => activeScope.value === scope.value);
  const result = shallowRef<Result & { filter: Filter }>();
  function end() {
    if (!playing.value) return;
    result.value = { ...summarize(), filter: routeFilter.value };
    activeScope.value = null;
    reset();
  }
  watch(scope, () => {
    if (route.path !== page) return;
    draft.value = routeFilter.value;
    if (!playing.value) { activeScope.value = null; result.value = undefined; reset(); }
  }, { immediate: true });
  async function start() {
    const target = new URLSearchParams(query.value).toString(), path = route.path;
    if (target !== scope.value) await router.replace({ path, query: query.value });
    if (path !== route.path || target !== scope.value || playing.value) return false;
    activeScope.value = target;
    result.value = undefined;
    return true;
  }
  return { playing, draft, query, result, start, end };
}
