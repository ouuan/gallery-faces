<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ChevronDown } from '@lucide/vue';
import { useMessage } from 'naive-ui';
import Filters from './Filters.vue';
import { emptyFilter, hasFilters, type Filter } from './filters';
import { rangeError } from './date-range';
import { useLibrary } from './store';

const filter = defineModel<Filter>({ required: true });
defineProps<{ face?: boolean }>();
const library = useLibrary(), message = useMessage();
const expanded = ref(matchMedia('(min-width: 760px)').matches || !!rangeError(filter.value.start, filter.value.end));
const summary = computed(() => {
  const { people, publishers, start, end, include_no_faces } = filter.value;
  return rangeError(start, end) || [people.length && `${people.length} 位人物`, publishers.length && `${publishers.length} 个发布者`,
    (start || end) && '已限日期', include_no_faces && '含无人脸图片'].filter(Boolean).join(' · ') || '未设置筛选';
});
onMounted(() => library.load().catch(cause => message.error(cause.message)));
</script>

<template>
  <section class="game-filters" aria-label="筛选照片">
    <button type="button" class="filter-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
      <strong>筛选照片</strong><span>{{ summary }}</span><ChevronDown aria-hidden="true" :size="16" />
    </button>
    <template v-if="expanded">
      <Filters v-model="filter" hide-heading :hide-no-faces="face" />
      <button v-if="hasFilters(filter)" type="button" class="text-button" @click="filter = emptyFilter()">清空</button>
    </template>
  </section>
</template>

<style scoped>
.game-filters { min-width: 0; container-type: inline-size; border-block: 1px solid var(--line); }
.filter-toggle { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 48px; padding: 4px 0; border: 0; background: none; color: var(--text); text-align: start; }
.filter-toggle strong { flex: none; font-size: 16px; }
.filter-toggle span { margin-inline-start: auto; color: var(--muted); text-align: end; }
.filter-toggle svg { flex: none; color: var(--muted); }
.filter-toggle[aria-expanded=true] svg { transform: rotate(180deg); }
.game-filters :deep(.filters) { gap: 16px 32px; padding-block: 8px 20px; }
.game-filters :deep(legend) { margin-bottom: 6px; }
@container (min-width: 38rem) {
  .game-filters :deep(.filters) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; }
  .game-filters :deep(.date-bounds) { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 32px; }
  .game-filters :deep(.date-field) { margin: 0; }
  .game-filters :deep(.date-range-hint) { grid-column: 1 / -1; }
}
</style>
