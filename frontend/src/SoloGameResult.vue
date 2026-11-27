<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NButton, NStatistic } from 'naive-ui';
import { RotateCcw } from '@lucide/vue';
import GameFilterSummary from './GameFilterSummary.vue';
import type { Filter } from './filters';

defineProps<{
  filter: Filter; count: number; label: string; value: string; unit?: string; detail: string;
  breakdown: { label: string; count: number; tone: 'success' | 'error' | 'muted' | 'accent' | 'amber' }[];
}>();
defineEmits<{ setup: [] }>();
const heading = ref<HTMLElement | null>(null);
onMounted(() => heading.value?.focus());
</script>

<template>
  <section class="solo-result" aria-labelledby="solo-result-title">
    <div class="result-heading"><h2 id="solo-result-title" ref="heading" tabindex="-1">本局结果</h2><span>已答 {{ count }} 题</span></div>
    <div class="report">
      <div class="measure">
        <n-statistic :label="label" :value="value" tabular-nums :theme-overrides="{ valueFontSize: '3.5rem', valueFontWeight: '650' }">
          <template v-if="unit" #suffix><span class="unit">{{ unit }}</span></template>
        </n-statistic>
        <p>{{ detail }}</p>
      </div>
      <section class="breakdown" aria-label="作答分布"><h3>作答分布</h3>
        <dl v-if="count"><div v-for="item in breakdown" :key="item.label" class="row">
          <dt>{{ item.label }}</dt><dd><span class="track" aria-hidden="true"><i :class="item.tone" :style="{ width: `${item.count / count * 100}%` }" /></span><span>{{ item.count }} 题</span></dd>
        </div></dl>
        <p v-else>本局尚未提交答案。</p>
      </section>
    </div>
    <GameFilterSummary class="result-filters" :filter="filter" />
    <n-button type="primary" @click="$emit('setup')"><template #icon><RotateCcw :size="17" aria-hidden="true" /></template>再来一局</n-button>
  </section>
</template>

<style scoped>
.solo-result { margin: 24px 0 32px; font-variant-numeric: tabular-nums; }
.result-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
h2, h3, p, dl, dd { margin: 0; }
.result-heading span, p, .unit { color: var(--muted); }
.report { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); align-items: center; gap: 40px; padding-block: 32px; border-bottom: 1px solid var(--line); }
.measure { min-width: 0; }
.result-filters { margin-top: 20px; }
.measure :deep(.n-statistic-value) { line-height: 1.18; overflow-wrap: anywhere; }
.unit { font-size: 20px; font-weight: 500; }
.measure p { margin-top: 12px; }
.breakdown h3 { margin-bottom: 12px; font-size: 16px; }
.row, dd { display: grid; align-items: center; gap: 12px; }
.row { grid-template-columns: 3em minmax(0, 1fr); padding-block: 6px; }
dd { grid-template-columns: minmax(0, 1fr) auto; text-align: end; }
dd > span:last-child { min-width: 4ch; }
.track { background: var(--line); height: 8px; border-radius: 2px; overflow: hidden; }
.track i { display: block; height: 100%; }
.success { background: var(--success); } .error { background: var(--error); } .muted { background: var(--muted); } .accent { background: var(--accent); }
.amber { background: var(--chart-amber); }
.solo-result button { margin-top: 24px; min-width: 9rem; }
@media (max-width: 600px) {
  .report { grid-template-columns: minmax(0, 1fr); gap: 24px; padding-block: 24px; }
  .solo-result button { width: 100%; }
}
</style>
