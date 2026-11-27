<script setup lang="ts">
import { computed, ref } from 'vue';
import { NButton, NDatePicker } from 'naive-ui';
import { ChevronLeft, ChevronRight } from '@lucide/vue';
import { dayLabel, dayNumber, difference, middleDay, type HistoryPhoto } from './history-quiz';
import LoadingOverlay from './LoadingOverlay.vue';

const props = defineProps<{ photo: HistoryPhoto | null; selected?: string | null; correct?: string | null; locked?: boolean; unanswered?: boolean }>();
const emit = defineEmits<{ choose: [date: string]; change: [date: string] }>();
const midpoint = computed(() => props.photo ? middleDay(props.photo) : 0);
const draft = ref(midpoint.value);
const day = computed(() => props.selected ? dayNumber(props.selected) : props.unanswered ? midpoint.value : draft.value);
const first = computed(() => props.photo ? dayNumber(props.photo.first_date) : 0), last = computed(() => props.photo ? dayNumber(props.photo.last_date) : 0);
const loaded = ref(false), failed = ref(false);
const disabled = computed(() => props.locked || !!props.correct || !loaded.value);
const firstLocal = computed(() => Date.parse(`${props.photo?.first_date}T00:00:00`));
const lastLocal = computed(() => Date.parse(`${props.photo?.last_date}T23:59:59.999`));
function outsideRange(timestamp: number) {
  return timestamp < firstLocal.value || timestamp > lastLocal.value;
}
function select(value: number) {
  draft.value = value;
  emit('change', dayLabel(value));
}
</script>

<template>
  <div class="history-board">
    <div class="picture">
      <div v-if="failed" role="alert">照片加载失败 <n-button @click="failed = false">重试加载照片</n-button></div>
      <img v-else-if="photo" :src="photo.image_url" :width="photo.width" :height="photo.height" alt="题目照片" @load="loaded = true" @error="loaded = false; failed = true" />
      <LoadingOverlay :show="!loaded && !failed" center :label="photo ? '正在加载照片…' : '正在出题…'" />
    </div>
    <section class="controls">
      <h2>这张照片最早发布于哪一天？</h2>
      <div class="date-step"><n-button quaternary circle aria-label="前一天" title="前一天" :disabled="disabled || day <= first" @click="select(day - 1)"><ChevronLeft :size="20" /></n-button>
        <output v-if="locked || correct || (photo && first === last)">{{ dayLabel(day) }}</output>
        <label v-else class="date-picker"><span class="sr-only">选择猜测日期</span>
          <n-date-picker type="date" value-format="yyyy-MM-dd" format="yyyy-MM-dd" input-readonly :actions="null"
            :disabled="disabled" :formatted-value="photo ? dayLabel(day) : null" :is-date-disabled="outsideRange" @update:formatted-value="select(dayNumber($event))" />
        </label>
        <n-button quaternary circle aria-label="后一天" title="后一天" :disabled="disabled || day >= last" @click="select(day + 1)"><ChevronRight :size="20" /></n-button></div>
      <input type="range" aria-label="猜测日期" :aria-valuetext="photo ? dayLabel(day) : undefined" :min="first" :max="last" step="1" :value="day" :disabled="disabled || first === last" @input="select(($event.target as HTMLInputElement).valueAsNumber)" />
      <div class="bounds"><span>{{ photo?.first_date }}</span><span>{{ photo?.last_date }}</span></div>
      <div v-if="correct" class="result" role="status"><strong>最早来源：{{ correct }}</strong><span>{{ unanswered ? '未答（按居中日期计）' : '你的猜测' }}：{{ dayLabel(day) }} · {{ difference(dayLabel(day), correct) }}</span></div>
      <n-button v-else-if="!locked" type="primary" :disabled="disabled" @click="emit('choose', dayLabel(day))">提交日期</n-button>
      <slot />
    </section>
  </div>
</template>

<style scoped>
.history-board { display: grid; grid-template-columns: minmax(0, 2fr) minmax(270px, 1fr); align-items: start; gap: 28px; }
.picture { position: sticky; top: calc(var(--site-header-height) + 12px); display: grid; place-items: center; height: 64svh; }
.picture img { width: 100%; height: 100%; object-fit: contain; min-height: 0; }
.controls { min-width: 0; }
.date-step, .bounds { display: flex; align-items: center; justify-content: space-between; font-variant-numeric: tabular-nums; }
.date-step { margin-top: 14px; }
.date-step button { width: 44px; height: 44px; }
.date-picker { width: 148px; max-width: calc(100% - 88px); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
output { font-size: 22px; font-weight: 600; }
input[type=range] { display: block; width: 100%; height: 44px; margin: 0; accent-color: var(--accent); }
.bounds { min-height: 1lh; color: var(--muted); font-size: 13px; margin-bottom: 16px; }
.result { display: grid; gap: 4px; padding-bottom: 12px; font-variant-numeric: tabular-nums; }
@media (max-width: 768px) and (orientation: portrait), (max-width: 599px) {
  .history-board { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .picture { position: relative; top: auto; width: 100%; height: clamp(9rem, calc(100svh - 24rem), 46svh); }
  .date-step { margin-top: 4px; }
}
</style>
