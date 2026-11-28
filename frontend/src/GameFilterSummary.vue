<script setup lang="ts">
import { computed, watch } from 'vue';
import { dateLabel, platformLabel } from './api';
import { hasFilters, type Filter } from './filters';
import { peopleOptions, pickerIndex } from './people-cascader';
import { useLibrary } from './store';

const props = defineProps<{ filter: Filter }>();
const library = useLibrary();
const peopleIndex = computed(() => pickerIndex(peopleOptions(library.people, library.groups)));
const publisherIndex = computed(() => pickerIndex(peopleOptions(library.people.filter(person => person.accounts.length), library.groups)));
function fallback(value: string) {
  const colon = value.indexOf(':'), platform = value.slice(0, colon), account = value.slice(colon + 1);
  return platform === 'person' ? library.people.find(person => person.id === Number(account))?.name ?? `人物 #${account}` : `${platformLabel(platform)} @${account}`;
}
const people = computed(() => peopleIndex.value.tagLabels(new Set(props.filter.people.map(id => `person:${id}`)), fallback));
const publishers = computed(() => publisherIndex.value.tagLabels(new Set(props.filter.publishers), fallback));
watch(() => !!props.filter.people.length || props.filter.publishers.some(value => value.startsWith('person:')), needed => {
  if (needed) void library.load().catch(() => {});
}, { immediate: true });
</script>
<template>
  <section class="room-filters" aria-label="出题筛选"><h3>出题筛选</h3>
    <p v-if="!hasFilters(filter)">未设置筛选</p>
    <dl v-else>
      <template v-if="filter.people.length"><dt>人物</dt><dd>{{ people.join('、') }}（{{ [filter.people.length > 1 ? filter.match === 'all' ? '全部同框' : '任一入镜' : '', filter.onlySelected ? '仅限所选' : '可含他人'].filter(Boolean).join('，') }}）</dd></template>
      <template v-if="filter.publishers.length"><dt>发布者</dt><dd>{{ publishers.join('、') }}</dd></template>
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
