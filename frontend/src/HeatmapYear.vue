<script setup lang="ts">
import { computed, ref, watch, watchPostEffect } from 'vue';
import { NHeatmap } from 'naive-ui';
import { ArrowUpRight } from '@lucide/vue';
import { calendarDays, dayQuery, type heatmapScale, type HeatmapDay, type Metric } from './heatmap';
import type { Filter } from './filters';

const props = defineProps<{ year: number; first: string; last: string; data: ReadonlyMap<string, HeatmapDay>; metric: Metric; scale: ReturnType<typeof heatmapScale>; filter: Filter }>();
const days = computed(() => calendarDays(props.year));
const series = computed(() => days.value.map(({ date, timestamp }) => {
  const count = props.data.get(date)?.[props.metric] ?? 0;
  return { timestamp, value: props.scale.findIndex(band => count <= band.end) };
}));
// NHeatmap normalizes each year to its own peak. A matching palette prefix keeps band indices unchanged.
const activeColors = computed(() => props.scale.slice(1, 1 + Math.max(...series.value.map(day => day.value))).map(band => band.color));
const enabled = computed(() => days.value.filter(day => day.date >= props.first && day.date <= props.last));
const total = computed(() => days.value.reduce((sum, { date }) => {
  const day = props.data.get(date);
  return day ? { new_photos: sum.new_photos + day.new_photos, posts: sum.posts + day.posts } : sum;
}, { new_photos: 0, posts: 0 }));
const calendar = ref<HTMLElement>();
const details = ref<HTMLElement>();
const pinned = ref(''), preview = ref(''), focusDate = ref('');
const active = computed(() => preview.value || pinned.value);
const counts = computed(() => active.value ? props.data.get(active.value) : total.value);
watch(pinned, (date, _, onCleanup) => {
  if (!date) return;
  function dismiss(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (calendar.value?.contains(target.closest('[data-date]')) || details.value?.contains(target.closest('a'))) return;
    pinned.value = preview.value = '';
  }
  document.addEventListener('click', dismiss, true);
  onCleanup(() => document.removeEventListener('click', dismiss, true));
});
watchPostEffect(() => {
  const body = calendar.value?.querySelector('tbody');
  if (!body) return;
  const tabStop = focusDate.value || enabled.value[0]?.date;
  for (const { date, row, column } of days.value) {
    const rect = body.rows[row]?.cells[column + 1]?.firstElementChild;
    if (!(rect instanceof HTMLElement)) continue;
    if (date < props.first || date > props.last) { rect.classList.add('outside'); continue; }
    const day = props.data.get(date);
    rect.dataset.date = date;
    rect.tabIndex = date === tabStop ? 0 : -1;
    rect.setAttribute('role', 'button');
    rect.setAttribute('aria-pressed', String(date === pinned.value));
    rect.setAttribute('aria-label', `${date}，${day?.new_photos ?? 0} 张新照片，${day?.posts ?? 0} 条帖子`);
  }
});
function eventDate(event: Event) { return event.target instanceof HTMLElement ? event.target.dataset.date || '' : ''; }
function move(event: KeyboardEvent) {
  const date = eventDate(event);
  if (!date) return;
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); pinned.value = date; return; }
  const steps: Record<string, number> = { ArrowUp: -1, ArrowDown: 1, ArrowLeft: -7, ArrowRight: 7 };
  if (!(event.key in steps)) return;
  event.preventDefault();
  const index = enabled.value.findIndex(day => day.date === date);
  const target = enabled.value[Math.max(0, Math.min(enabled.value.length - 1, index + steps[event.key]))];
  if (target) calendar.value?.querySelector<HTMLElement>(`[data-date="${target.date}"]`)?.focus();
}
</script>

<template>
  <section class="heat-year" :aria-labelledby="`year-${year}`">
    <h2 :id="`year-${year}`">{{ year }} 年</h2>
    <div ref="calendar" class="year-scroll" @pointerover="preview = eventDate($event)" @pointerleave="preview = ''"
      @focusin="focusDate = preview = eventDate($event)" @focusout="preview = ''" @click="eventDate($event) && (pinned = eventDate($event))" @keydown="move">
      <n-heatmap :data="series" :first-day-of-week="0" :minimum-color="scale[0].color" :active-colors="activeColors" :show-color-indicator="false"
        :x-gap="3" :y-gap="3" :theme-overrides="{ rectSizeMedium: 'var(--day-size)' }" />
    </div>
    <div ref="details" class="year-details"><strong>{{ active || '全年合计' }}</strong><span>{{ counts?.new_photos ?? 0 }} 张新照片 · {{ counts?.posts ?? 0 }} 条帖子</span>
      <router-link v-if="pinned && active === pinned" :to="{ path: '/', query: dayQuery(filter, pinned) }">查看图库<ArrowUpRight :size="15" aria-hidden="true" /></router-link>
    </div>
  </section>
</template>

<style scoped>
.heat-year { padding-block: 20px 12px; border-top: 1px solid var(--line); }
.heat-year h2 { margin: 0 0 12px; }
.year-scroll { --day-size: 14px; overflow-x: auto; scrollbar-width: thin; }
.year-scroll :deep(table) { width: max-content; }
.year-scroll :deep(.outside) { background: transparent; border: 1px dashed var(--line); }
.year-scroll :deep([data-date]) { cursor: pointer; }
.year-scroll :deep([data-date]:is(:hover, :focus-visible, [aria-pressed=true])) { outline: 2px solid var(--text); outline-offset: 1px; }
.year-details { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; min-height: 44px; font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }
.year-details strong { color: var(--text); }
.year-details a { display: inline-flex; align-items: center; gap: 2px; min-height: 44px; }
@media (max-width: 720px) { .year-scroll { --day-size: 21px; } }
</style>
