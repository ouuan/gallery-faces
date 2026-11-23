<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId } from 'vue';
import { NTooltip } from 'naive-ui';
import { dateLabel } from './api';
import { socialTime, useClock } from './social-time';

const props = defineProps<{ value: string; inCard?: boolean }>();
const now = useClock();
const full = computed(() => Number.isFinite(Date.parse(props.value)) ? dateLabel(props.value) : '缺少日期');
const element = ref<HTMLElement>();
const tooltipId = useId();
const anchor = ref<{ x: number; y: number }>();
let card: HTMLElement | null;
function show() {
  const box = element.value?.getBoundingClientRect();
  if (box) anchor.value = { x: box.left + box.width / 2, y: box.top };
}
function hide() {
  anchor.value = undefined;
  document.removeEventListener('pointerdown', outside, true);
}
function outside(event: Event) { if (!element.value?.contains(event.target as Node)) hide(); }
function openTip() {
  show();
  document.addEventListener('pointerdown', outside, true);
}
onMounted(() => {
  card = props.inCard ? element.value?.closest('button') ?? null : null;
  card?.addEventListener('focus', show);
  card?.addEventListener('blur', hide);
});
onUnmounted(() => {
  card?.removeEventListener('focus', show);
  card?.removeEventListener('blur', hide);
  document.removeEventListener('pointerdown', outside, true);
});
</script>
<template>
  <time ref="element" :datetime="value" :aria-label="full" :aria-describedby="anchor ? tooltipId : undefined" :tabindex="inCard ? undefined : 0"
    @pointerenter="show" @pointerleave="hide" @focus="show" @blur="hide" @click.stop="openTip" @keydown.esc="hide">{{ socialTime(value, now) }}</time>
  <n-tooltip v-if="anchor" :show="true" trigger="manual" :x="anchor.x" :y="anchor.y" :animated="false"><span :id="tooltipId" role="tooltip">{{ full }}</span></n-tooltip>
</template>
