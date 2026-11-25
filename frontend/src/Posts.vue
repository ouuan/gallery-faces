<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NSelect, NDrawer, NDrawerContent, NAlert } from 'naive-ui';
import Filters from './Filters.vue';
import PostEmbed, { type Post } from './PostEmbed.vue';
import { api, ApiError } from './api';
import { useLibrary } from './store';
import { usePageTitle } from './page-title';
import { emptyFilter, fromQuery, toQuery, clearFilters, type Filter } from './filters';
import { rangeError } from './date-range';
usePageTitle('投稿一覧');
const route = useRoute(), router = useRouter(), store = useLibrary();
const filter = computed(() => fromQuery(route.query));
const draft = ref(emptyFilter()), drawer = ref(false), items = ref<Post[]>([]), cursor = ref<string | null>(null);
const loading = ref(false), error = ref(''); let controller: AbortController | undefined; let version = 0;
const apply = (value: Filter) => router.push({ query: toQuery(value) });
function closeFilters() { if (drawer.value) { void apply(draft.value); drawer.value = false; } }
async function load(more = false) {
  if (more && (loading.value || !cursor.value)) return;
  controller?.abort(); controller = new AbortController(); const current = ++version;
  error.value = rangeError(filter.value.start, filter.value.end);
  if (!more) { items.value = []; cursor.value = null; }
  if (error.value) { loading.value = false; return; }
  loading.value = true;
  try {
    const q = new URLSearchParams(toQuery(filter.value)); if (more && cursor.value) q.set('cursor', cursor.value);
    const result = await api<{ items: Post[]; next_cursor: string | null }>('/posts?' + q, { signal: controller.signal });
    if (current !== version) return;
    items.value = [...new Map([...(more ? items.value : []), ...result.items].map(p => [p.key, p])).values()]; cursor.value = result.next_cursor;
  } catch (err) {
    if (current === version) error.value = err instanceof ApiError && [400, 414].includes(err.status)
      ? err.message : '投稿を読み込めませんでした。もう一度お試しください';
  }
  finally { if (current === version) loading.value = false; }
}
watch(() => JSON.stringify(toQuery(filter.value)), () => load(), { immediate: true });
async function loadLibrary() { try { await store.load(); } catch { error.value = '人物一覧を読み込めませんでした'; } }
onMounted(loadLibrary);
onBeforeUnmount(() => { version++; controller?.abort(); });
</script>
<template>
  <main class="posts-shell">
    <aside class="posts-filters"><Filters :model-value="filter" @update:model-value="apply" @clear="apply(clearFilters(filter))" /></aside>
    <div class="posts-content" :aria-busy="loading">
      <div class="posts-toolbar">
        <div><h1>投稿一覧</h1><p class="muted">人物・投稿者・投稿日で絞り込み</p></div>
        <div class="posts-actions">
          <n-button class="posts-filter-toggle" @click="draft = { ...filter, people: [...filter.people], publishers: [...filter.publishers] }; drawer = true">絞り込み</n-button>
          <n-select aria-label="並び順" :value="filter.sort" :options="[{label:'新しい順',value:'newest'},{label:'古い順',value:'oldest'}]" @update:value="apply({...filter, sort: $event})" />
        </div>
      </div>
      <n-alert v-if="error" type="error">{{ error }} <n-button @click="load(!!cursor); loadLibrary()">再試行</n-button></n-alert>
      <div class="post-timeline">
        <PostEmbed v-for="post in items" :key="post.key" :post="post" />
        <p v-if="loading && !items.length" class="post-list-status muted" role="status">投稿を読み込み中…</p>
        <p v-else-if="!items.length && !error" class="empty-state">条件に合う投稿が見つかりません</p>
        <n-button v-if="cursor" class="post-load-more stable-loading-button" :loading="loading" @click="load(true)">もっと見る</n-button>
      </div>
    </div>
    <n-drawer :show="drawer" placement="left" width="min(340px, 100vw)" @update:show="!$event && closeFilters()">
      <n-drawer-content :native-scrollbar="false" :body-content-style="{ padding: '24px' }" aria-label="投稿を絞り込む"><Filters v-model="draft" contained @clear="draft = clearFilters(draft)" /><template #footer><n-button @click="closeFilters">絞り込みを適用</n-button></template></n-drawer-content>
    </n-drawer>
  </main>
</template>
<style scoped>
/* 4px spacing scale: 8px within controls, 24px between groups, 32px page inset. */
.posts-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  width: 100%;
  max-width: 1120px;
  margin-inline: auto;
  flex: 1;
  min-height: 0;
}
.posts-filters {
  min-width: 0;
  padding: 32px 24px;
  background: var(--panel);
  border-inline: 1px solid var(--line);
}
.posts-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
  width: 100%;
  max-width: 614px; /* 550px embed plus page insets. */
  min-width: 0;
  padding: 32px;
  justify-self: center;
}
.posts-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}
.posts-toolbar p { margin-top: 4px; }
.posts-actions { display: flex; gap: 8px; }
.posts-actions .n-select { width: 120px; }
.posts-filter-toggle { display: none; }
.post-timeline { display: grid; gap: 24px; min-width: 0; }
.post-list-status { display: grid; place-items: center; min-height: 300px; }
.post-load-more { justify-self: center; min-width: 160px; }
@media (max-width: 900px) {
  .posts-shell { grid-template-columns: minmax(0, 1fr); }
  .posts-filters { display: none; }
  .posts-filter-toggle { display: inline-flex; }
}
@media (max-width: 640px) {
  .posts-content {
    max-width: 582px;
    padding: 24px max(16px, env(safe-area-inset-right)) max(24px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
  }
  .posts-toolbar { align-items: stretch; flex-direction: column; }
  .posts-actions > * { flex: 1; min-width: 0; }
  .posts-actions .n-select { width: auto; }
}
</style>
