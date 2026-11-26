<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Images, Link } from '@lucide/vue';
import { NButton } from 'naive-ui';
import { api, ApiError } from './api';
import { filterOnlyQuery, fromQuery } from './filters';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import type { components } from './schema';
import LoadingOverlay from './LoadingOverlay.vue';

const props = defineProps<{ mode: 'daily' | 'random' }>();
const route = useRoute();
const title = computed(() => {
  const value = route.query.title;
  return (Array.isArray(value) ? value[0] : value)?.trim() || (props.mode === 'daily' ? '每日一图' : '随机图片');
});
usePageTitle(title);
const query = computed(() => filterOnlyQuery(fromQuery(route.query)));
const suffix = computed(() => {
  const params = new URLSearchParams(query.value).toString();
  return params ? `?${params}` : '';
});
const latest = useLatestRequest();
const photo = ref<components['schemas']['PhotoDraw'] | null>(null);
const imageLoaded = ref(false);
const error = ref('');
const empty = ref(false);

async function load() {
  const signal = latest.start();
  photo.value = null;
  imageLoaded.value = false;
  error.value = '';
  empty.value = false;
  try {
    const result = await api<components['schemas']['PhotoDraw']>(`/gallery/${props.mode}${suffix.value}`, { signal });
    if (!signal.aborted) photo.value = result;
  } catch (cause) {
    if (signal.aborted) return;
    empty.value = cause instanceof ApiError && cause.status === 404;
    error.value = (cause as Error).message;
  }
}
watch([() => props.mode, suffix], load, { immediate: true });
</script>

<template>
  <main class="draw-page">
    <header class="draw-header">
      <div class="draw-title">
        <h1>{{ title }}</h1>
        <time v-if="mode === 'daily' && photo" :datetime="photo.date">{{ photo.date }}</time>
      </div>
      <nav :aria-label="`${title}链接`">
        <router-link :to="{ path: '/', query: photo ? { ...query, photo: photo.group_id } : query }">
          <Images :size="17" aria-hidden="true" />{{ photo ? '在图库中查看' : '返回图库' }}
        </router-link>
        <a :href="`/api/v1/gallery/${mode}/image${suffix}`"><Link :size="17" aria-hidden="true" />图片直链</a>
      </nav>
    </header>
    <div class="draw-picture" :aria-busy="!error && !imageLoaded">
      <div v-if="error" class="draw-message" role="status">
        <p>{{ error }}</p><n-button v-if="!empty" @click="load">重试</n-button>
      </div>
      <img v-else-if="photo" :src="photo.image_url" :alt="mode === 'daily' ? `${photo.date} 的${title}` : title"
        @load="imageLoaded = true" @error="error = '照片加载失败，请重试'" />
      <LoadingOverlay :show="!error && !imageLoaded" center :label="`正在加载${title}`" />
    </div>
  </main>
</template>

<style scoped>
.draw-page { width: min(100%, 1440px); margin-inline: auto; padding: 20px 28px 24px; }
.draw-header, .draw-title, nav, nav a { display: flex; align-items: center; }
.draw-header { justify-content: space-between; flex-wrap: wrap; gap: 4px 24px; margin-bottom: 12px; }
.draw-title { gap: 12px; max-width: 100%; }
.draw-title h1 { overflow-wrap: anywhere; }
time { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
nav { gap: 20px; }
nav a { gap: 6px; min-height: 44px; }
.draw-picture { position: relative; display: grid; place-items: center; min-height: 240px; }
.draw-picture img { display: block; max-width: 100%; max-height: calc(100svh - 210px); border-radius: 4px; }
.draw-message { text-align: center; color: var(--muted); }
.draw-message button { margin-top: 12px; }
@media (max-width: 600px) {
  .draw-page { padding: 16px; }
  .draw-header { align-items: flex-start; flex-direction: column; }
  .draw-picture img { max-height: calc(100svh - 260px); }
}
</style>
