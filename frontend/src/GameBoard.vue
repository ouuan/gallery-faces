<script setup lang="ts">
import { computed, ref, watch, watchEffect } from 'vue';
import { Check, X, ZoomIn } from '@lucide/vue';
import { NButton } from 'naive-ui';
import { facePosition } from './api';
import { cropBox, faceZoom, gridViewport } from './face-game';
import { visibleCells } from './face-grid';
import LoadingOverlay from './LoadingOverlay.vue';
import type { components } from './schema';

const props = defineProps<{ photo?: components['schemas']['RoomPhoto'] | null; cropped: boolean; revealed: boolean;
  locked: boolean; selected?: number | null; correctId?: number | null; answerName?: string | null; voided?: boolean;
  order?: number[]; started?: number | null; interval?: number; wrongChoices?: (number | null)[];
  tallies?: components['schemas']['ChoiceTally'][] | null }>();
const emit = defineEmits<{ choose: [choice: number | null, cells: number]; loaded: [] }>();
const imageReady = ref(false), failed = ref(false), zoomed = ref(false);
const grid = computed(() => !!props.order && !props.revealed);
const crop = computed(() => props.cropped && !grid.value && !props.revealed);
const shown = ref(0);
watchEffect(cleanup => {
  const order = props.order, start = props.started, seconds = props.interval;
  shown.value = 0;
  if (!grid.value || !imageReady.value || !order || start == null || !seconds) return;
  let timer: number;
  function tick() {
    const elapsed = performance.now() - start!;
    const count = visibleCells(elapsed, seconds!, order!.length);
    shown.value = count;
    if (count < order!.length) timer = window.setTimeout(tick, Math.max(1, (count + 1) * seconds! * 1000 - elapsed));
  }
  tick(); cleanup(() => clearTimeout(timer));
});
const visible = computed(() => new Set(props.order?.slice(0, shown.value)));
const choices = computed(() => [...(props.photo?.choices ?? []), { id: null, name: '都不是' }].map(choice => ({
  ...choice, tally: props.revealed ? props.tallies?.find(item => item.choice === choice.id) : undefined,
})));
const bounds = computed(() => {
  const photo = props.photo;
  if (!photo) return [0, 0, 1, 1] as const;
  if (grid.value) return gridViewport(photo.box, photo.width, photo.height);
  if (crop.value) return cropBox(photo.box, photo.width, photo.height);
  return [0, 0, photo.width, photo.height] as const;
});
const frame = computed(() => {
  const [, , width, height] = bounds.value;
  const ratio = width / height;
  const nativeWidth = grid.value && props.photo ? Math.min(props.photo.width, props.photo.height * ratio) : width;
  return { width: `min(100%, ${crop.value ? '100%' : nativeWidth + 'px'}, ${ratio * 100}cqh)`, aspectRatio: `${width} / ${height}` };
});
watch([crop, () => props.revealed], () => { zoomed.value = false; });
function holdZoom(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0 || !imageReady.value) return;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  zoomed.value = true;
}
const targetStyle = computed(() => {
  if (!props.photo) return;
  const { box } = props.photo;
  const [left, top, width, height] = bounds.value;
  return facePosition([box[0]! - left, box[1]! - top, box[2]!, box[3]!], width, height);
});
const imageStyle = computed(() => {
  if (!props.photo) return;
  const { width, height } = props.photo;
  if (crop.value || grid.value) {
    const [left, top, cropWidth, cropHeight] = bounds.value;
    return { width: width / cropWidth * 100 + '%', height: height / cropHeight * 100 + '%', left: -left / cropWidth * 100 + '%', top: -top / cropHeight * 100 + '%' };
  }
  if (!zoomed.value) return;
  const { scale, left, top } = faceZoom(props.photo.box, width, height);
  return { transform: `translate(${left * 100}%, ${top * 100}%) scale(${scale})` };
});
</script>

<template>
  <div class="game-layout">
    <div class="game-picture">
      <slot v-if="!photo" name="placeholder" />
      <div v-else-if="failed" role="alert">照片加载失败 <n-button @click="failed = false">重试加载照片</n-button></div>
      <div v-else class="game-frame" :style="frame">
        <img :src="photo.image_url" :style="imageStyle" alt="题目照片" @load="imageReady = true; emit('loaded')" @error="imageReady = false; failed = true" />
        <div v-if="grid && order" class="grid-mask" aria-hidden="true" :style="{ '--side': Math.sqrt(order.length) }">
          <i v-for="cell in order.length" :key="cell" :class="{ covered: !visible.has(cell - 1) }" />
        </div>
        <span v-if="imageReady && !crop && !zoomed" class="target-face" :class="{ 'grid-target': grid }" :style="targetStyle" aria-label="要辨认的人脸" />
        <LoadingOverlay :show="!imageReady" center label="正在加载照片…" />
      </div>
    </div>
    <div v-if="photo" class="game-controls">
        <div class="game-prompt-row">
          <h2 id="game-prompt">{{ crop ? '这是谁？' : '框中的是谁？' }}</h2>
          <span v-if="grid && order" class="grid-progress">已显示 {{ shown }} / {{ order.length }} 格</span>
          <n-button v-if="!crop && !grid" quaternary circle :disabled="!imageReady" aria-label="按住放大人脸" title="按住放大人脸"
            @pointerdown="holdZoom" @lostpointercapture="zoomed = false" @contextmenu.prevent
            @keydown.space.enter.prevent="zoomed = true" @keyup.space.enter.prevent="zoomed = false" @blur="zoomed = false">
            <ZoomIn :size="18" aria-hidden="true" />
          </n-button>
        </div>
        <div class="game-options" role="group" aria-labelledby="game-prompt">
          <button v-for="choice in choices" :key="choice.id ?? 'none'" type="button" :disabled="locked || !imageReady || (grid && shown === 0) || wrongChoices?.includes(choice.id)"
            :aria-description="!voided && wrongChoices?.includes(choice.id) ? '已答错' : undefined"
            :class="{ fallback: choice.id === null, selected: !revealed && choice.id === selected, right: revealed && !voided && choice.id === correctId, wrong: !voided && (wrongChoices?.includes(choice.id) || (revealed && choice.id === selected && choice.id !== correctId)) }"
            @click="emit('choose', choice.id, shown)">
            <span class="option-label">{{ choice.name }}<template v-if="revealed && !voided && choice.id === null && correctId === null && answerName">（{{ answerName }}）</template>
              <small v-if="choice.tally" class="option-tally" :title="choice.tally.nickname ?? undefined">{{ choice.tally.nickname ?? `${choice.tally.count} 人` }}</small>
            </span>
            <Check v-if="revealed && !voided && choice.id === correctId" :size="16" aria-hidden="true" />
            <X v-else-if="!voided && (wrongChoices?.includes(choice.id) || (revealed && choice.id === selected))" :size="16" aria-hidden="true" />
          </button>
        </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.game-layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 28px; align-items: start; }
.game-picture { position: sticky; top: calc(var(--site-header-height) + 16px); display: grid; grid-template: 100% / 100%; place-items: center; container-type: size; height: 64svh; }
.game-frame { position: relative; overflow: hidden; border-radius: 4px; }
.grid-mask { position: absolute; inset: -1px; display: grid; grid-template: repeat(var(--side), 1fr) / repeat(var(--side), 1fr); pointer-events: none; }
.grid-mask .covered { background: var(--panel); box-shadow: inset 0 0 0 1px var(--line); }
.grid-progress { margin-inline-start: 8px; color: var(--muted); font-variant-numeric: tabular-nums; }
.game-frame img { position: absolute; inset: 0; width: 100%; height: 100%; max-width: none; transform-origin: top left; }
.target-face { position: absolute; border: 3px solid white; outline: 2px solid #222; pointer-events: none; }
.grid-target { border-width: 2px; outline-width: 1px; opacity: .65; }
.game-controls { min-width: 0; }
.game-prompt-row { display: flex; align-items: center; flex-wrap: wrap; min-height: 44px; gap: 4px; }
.game-prompt-row button { width: 44px; height: 44px; touch-action: none; user-select: none; }
.game-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.game-options button {
  display: grid; grid-template-columns: minmax(0, 1fr) 16px; align-items: center; gap: 8px;
  min-height: 44px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--panel); color: var(--text); font-size: 14px; line-height: 1.6; text-align: start; overflow-wrap: anywhere;
}
.game-options .fallback, .game-options button:first-child:nth-last-child(2) { grid-column: 1 / -1; }
.game-options .fallback { background: transparent; color: var(--muted); }
.option-label { min-width: 0; }
.option-tally { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }
.game-options button:disabled { cursor: default; color: var(--muted); }
@media (hover: hover) { .game-options button:enabled:hover { border-color: var(--accent); color: var(--accent); } }
.game-options button.right { border-color: var(--success); background: var(--success-bg); color: var(--success); }
.game-options button.wrong { border-color: var(--error); color: var(--error); }
.game-options button.selected { border-color: var(--accent); color: var(--accent); }
@media (max-width: 768px) and (orientation: portrait), (max-width: 599px) {
  .game-layout { grid-template-columns: minmax(0, 1fr); gap: 8px; }
  .game-picture { position: relative; top: auto; height: clamp(8rem, calc(100svh - var(--game-control-reserve, 29rem) - env(safe-area-inset-bottom)), min(48svh, 75vw)); }
  .game-options { margin-top: 4px; }
}
@media (min-width: 600px) and (orientation: landscape) and (max-height: 540px) {
  .game-layout { grid-template-columns: minmax(0, 1fr) minmax(280px, 1fr); gap: 16px; }
  .game-picture { height: max(9rem, calc(100svh - var(--site-header-height) - 7rem)); }
  .game-options { margin-top: 4px; }
}
</style>
