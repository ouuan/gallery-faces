<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NAlert, NButton, NDrawer, NDrawerContent, NRadioButton, NRadioGroup, useMessage } from 'naive-ui';
import { CalendarDays, SlidersHorizontal } from '@lucide/vue';
import { api } from './api';
import { rangeError } from './date-range';
import { clearFilters, filterOnlyQuery, fromQuery, hasFilters, type Filter } from './filters';
import { heatmapRange, heatmapScale, type HeatmapDay, type Metric } from './heatmap';
import { usePageTitle } from './page-title';
import { useLibrary } from './store';
import { useLatestRequest } from './use-latest-request';
import Filters from './Filters.vue';
import HeatmapYear from './HeatmapYear.vue';
import LoadingOverlay from './LoadingOverlay.vue';

usePageTitle('热力图');
const route = useRoute(), router = useRouter(), library = useLibrary(), message = useMessage();
const filter = computed(() => fromQuery(route.query));
const query = computed(() => new URLSearchParams(filterOnlyQuery(filter.value)).toString());
const drawer = ref(false), draft = ref(filter.value);
const metric = ref<Metric>('new_photos');
const days = shallowRef<HeatmapDay[]>([]), loading = ref(true), error = ref('');
const range = computed(() => heatmapRange(filter.value.start, filter.value.end, days.value));
const data = computed(() => new Map(days.value.map(day => [day.date, day])));
const scale = computed(() => heatmapScale(days.value.map(day => day[metric.value])));
const requests = useLatestRequest();
const visibleYears = ref(12);
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
function apply(value: Filter) { return router.push({ path: '/heatmap', query: filterOnlyQuery(value) }); }
function openFilters() { draft.value = filter.value; drawer.value = true; }
function closeFilters() { if (drawer.value) { drawer.value = false; void apply(draft.value); } }
async function load() {
  const signal = requests.start();
  days.value = [];
  visibleYears.value = 12;
  error.value = rangeError(filter.value.start, filter.value.end);
  loading.value = !error.value;
  if (error.value) return;
  const params = new URLSearchParams(query.value);
  params.set('timezone', zone);
  try {
    const result = await api<HeatmapDay[]>('/gallery/heatmap?' + params, { signal });
    if (!signal.aborted) days.value = result;
  } catch (cause) {
    if (!signal.aborted) error.value = (cause as Error).message;
  } finally { if (!signal.aborted) loading.value = false; }
}
watch(query, load, { immediate: true });
onMounted(() => library.load().catch(cause => message.error(cause.message)));
</script>

<template>
  <main class="gallery-shell">
    <aside class="desktop-filters"><Filters :model-value="filter" @update:model-value="apply" @clear="apply(clearFilters(filter))" /></aside>
    <div class="gallery-content heatmap">
      <header class="heat-heading"><h1>热力图</h1><n-button class="mobile-filter" @click="openFilters"><template #icon><SlidersHorizontal /></template>筛选</n-button></header>
      <div class="heat-tools">
        <n-radio-group v-model:value="metric" aria-label="统计指标" role="radiogroup"><n-radio-button value="new_photos">新照片</n-radio-button><n-radio-button value="posts">帖子</n-radio-button></n-radio-group>
        <div v-if="!loading && !error && range" class="heat-legend" role="group" :aria-label="metric === 'posts' ? '帖子数图例' : '新照片数图例'">
          <span v-for="band in scale" :key="band.end"><i aria-hidden="true" :style="{ backgroundColor: band.color }" />{{ band.label }}</span>
        </div>
      </div>
      <div class="heat-results loading-region" :aria-busy="loading">
        <LoadingOverlay v-if="loading" show center label="正在加载热力图" />
        <n-alert v-else-if="error" type="error" title="无法显示热力图">{{ error }} <button v-if="!rangeError(filter.start, filter.end)" class="text-button" @click="load">重试</button></n-alert>
        <template v-else-if="range">
          <HeatmapYear v-for="year in range.years.slice(0, visibleYears)" :key="year" :year="year" :first="range.first" :last="range.last" :data="data" :metric="metric" :scale="scale" :filter="filter" />
          <n-button v-if="visibleYears < range.years.length" @click="visibleYears += 12">显示更早年份</n-button>
        </template>
        <div v-else class="empty-state"><CalendarDays :size="44" :stroke-width="1" /><h2>当前范围内没有照片或帖子</h2><n-button v-if="hasFilters(filter)" @click="apply(clearFilters(filter))">清空筛选</n-button></div>
      </div>
    </div>
  </main>
  <n-drawer :show="drawer" placement="left" width="min(340px, 100vw)" aria-label="筛选照片" @update:show="!$event && closeFilters()">
    <n-drawer-content><Filters v-model="draft" contained @clear="draft = clearFilters(draft)" /><template #footer><n-button type="primary" block @click="closeFilters">应用筛选</n-button></template></n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.heat-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.heat-tools { max-width: 1000px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px 24px; padding-bottom: 20px; }
.heat-legend, .heat-legend span { display: flex; align-items: center; }
.heat-legend { flex-wrap: wrap; gap: 4px 12px; font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }
.heat-legend span { gap: 4px; }
.heat-legend i { width: 12px; height: 12px; border-radius: 2px; }
.heat-results { min-height: 180px; max-width: 1000px; }
</style>
