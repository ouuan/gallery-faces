<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { dateLabel, platformLabel } from './api';
import { fromQuery, hasFilters } from './filters';
import { useLibrary } from './store';
import type { components } from './schema';

const props = defineProps<{ filters: components['schemas']['GameFilters'] }>();
const library = useLibrary();
const filter = computed(() => fromQuery({ ...props.filters, include_no_faces: String(props.filters.include_no_faces) }));
const name = (id: number) => library.people.find(person => person.id === id)?.name ?? `人物 #${id}`;
const publishers = computed(() => filter.value.publishers.map(value => {
  const colon = value.indexOf(':'), platform = value.slice(0, colon), account = value.slice(colon + 1);
  return platform === 'person' ? name(Number(account)) : `${platformLabel(platform)} @${account}`;
}));
onMounted(() => {
  if (filter.value.people.length || filter.value.publishers.some(value => value.startsWith('person:'))) void library.load().catch(() => {});
});
</script>
<template>
  <section class="room-filters" aria-label="出题筛选"><h3>出题筛选</h3>
    <p v-if="!hasFilters(filter)">未设置筛选</p>
    <dl v-else>
      <template v-if="filter.people.length"><dt>人物</dt><dd>{{ filter.people.map(name).join('、') }}（{{ [filter.people.length > 1 ? filter.match === 'all' ? '全部同框' : '任一入镜' : '', filter.onlySelected ? '仅限所选' : '可含他人'].filter(Boolean).join('，') }}）</dd></template>
      <template v-if="publishers.length"><dt>发布者</dt><dd>{{ publishers.join('、') }}</dd></template>
      <template v-if="filter.start"><dt>开始时间</dt><dd>{{ dateLabel(filter.start) }}</dd></template>
      <template v-if="filter.end"><dt>结束时间</dt><dd>{{ dateLabel(filter.end) }}（不含）</dd></template>
      <template v-if="filter.include_no_faces"><dt>照片范围</dt><dd>包含无人脸图片</dd></template>
    </dl>
  </section>
</template>
<style scoped>
.room-filters h3 { margin: 0 0 6px; font-size: 1em; }
.room-filters dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; margin: 0; }
.room-filters dt, .room-filters p { color: var(--muted); }
.room-filters dd, .room-filters p { margin: 0; overflow-wrap: anywhere; }
</style>
