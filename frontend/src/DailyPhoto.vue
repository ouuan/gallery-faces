<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { Images, Link } from '@lucide/vue';
import { NButton } from 'naive-ui';
import { api, ApiError } from './api';
import { dailyQuery, fromQuery } from './filters';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import type { components } from './schema';
import LoadingOverlay from './LoadingOverlay.vue';

const route = useRoute();
const title = computed(() => {
  const value = route.query.title;
  return (Array.isArray(value) ? value[0] : value)?.trim() || '每日一图';
});
usePageTitle(title);
const query = computed(() => dailyQuery(fromQuery(route.query)));
const suffix = computed(() => {
  const params = new URLSearchParams(query.value).toString();
  return params ? `?${params}` : '';
});
const latest = useLatestRequest();
const photo = ref<components['schemas']['DailyPhoto'] | null>(null);
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
    const result = await api<components['schemas']['DailyPhoto']>('/gallery/daily' + suffix.value, { signal });
    if (!signal.aborted) photo.value = result;
  } catch (cause) {
    if (signal.aborted) return;
    empty.value = cause instanceof ApiError && cause.status === 404;
    error.value = (cause as Error).message;
  }
}
watch(suffix, load, { immediate: true });
</script>

<template>
  <main class="daily-page">
    <header class="daily-header">
      <div class="daily-title">
        <h1>{{ title }}</h1>
        <time v-if="photo" :datetime="photo.date">{{ photo.date }}</time>
      </div>
      <nav :aria-label="`${title}链接`">
        <router-link :to="{ path: '/', query: photo ? { ...query, photo: photo.group_id } : query }">
          <Images :size="17" aria-hidden="true" />{{ photo ? '在图库中查看' : '返回图库' }}
        </router-link>
        <a :href="'/api/v1/gallery/daily/image' + suffix"><Link :size="17" aria-hidden="true" />图片直链</a>
      </nav>
    </header>
    <div class="daily-picture" :aria-busy="!error && !imageLoaded">
      <div v-if="error" class="daily-message" role="status">
        <p>{{ error }}</p><n-button v-if="!empty" @click="load">重试</n-button>
      </div>
      <img v-else-if="photo" :src="photo.image_url" :alt="`${photo.date} 的${title}`"
        @load="imageLoaded = true" @error="error = '照片加载失败，请重试'" />
      <LoadingOverlay :show="!error && !imageLoaded" center :label="`正在加载${title}`" />
    </div>
  </main>
</template>

<style scoped>
.daily-page { width: min(100%, 1440px); margin-inline: auto; padding: 20px 28px 24px; }
.daily-header, .daily-title, nav, nav a { display: flex; align-items: center; }
.daily-header { justify-content: space-between; flex-wrap: wrap; gap: 4px 24px; margin-bottom: 12px; }
.daily-title { gap: 12px; max-width: 100%; }
.daily-title h1 { overflow-wrap: anywhere; }
time { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
nav { gap: 20px; }
nav a { gap: 6px; min-height: 44px; }
.daily-picture { position: relative; display: grid; place-items: center; min-height: 240px; }
.daily-picture img { display: block; max-width: 100%; max-height: calc(100svh - 210px); border-radius: 4px; }
.daily-message { text-align: center; color: var(--muted); }
.daily-message button { margin-top: 12px; }
@media (max-width: 600px) {
  .daily-page { padding: 16px; }
  .daily-header { align-items: flex-start; flex-direction: column; }
  .daily-picture img { max-height: calc(100svh - 260px); }
}
</style>
