<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useId, watch } from 'vue';
import { NTooltip } from 'naive-ui';
import { dateLabel } from './api';
import { socialTime, useClock } from './social-time';

const props = defineProps<{ value: string; inCard?: boolean; disabled?: boolean }>();
const now = useClock();
const full = computed(() => Number.isFinite(Date.parse(props.value)) ? dateLabel(props.value) : '缺少日期');
const element = ref<HTMLElement>();
const tooltipId = useId();
const visible = ref(false);
let card: HTMLElement | null;
function show() {
  if (!props.disabled) visible.value = true;
}
function hide() {
  visible.value = false;
}
function outside(event: Event) { if (!element.value?.contains(event.target as Node)) hide(); }
function onFocus(event: FocusEvent) {
  if ((event.currentTarget as HTMLElement).matches(':focus-visible')) show();
}
function onCardKey(event: KeyboardEvent) { if (event.key === 'Escape') hide(); }
watch(() => props.disabled, disabled => { if (disabled) hide(); });
onMounted(() => {
  card = props.inCard ? element.value?.closest('button') ?? null : null;
  card?.addEventListener('focus', onFocus);
  card?.addEventListener('blur', hide);
  card?.addEventListener('keydown', onCardKey);
});
onUnmounted(() => {
  card?.removeEventListener('focus', onFocus);
  card?.removeEventListener('blur', hide);
  card?.removeEventListener('keydown', onCardKey);
});
</script>
<template>
  <n-tooltip :show="visible" :disabled="disabled" trigger="manual" :animated="false" @clickoutside="outside">
    <template #trigger>
      <time ref="element" :datetime="value" :aria-label="full" :aria-describedby="visible ? tooltipId : undefined" :tabindex="inCard ? undefined : 0"
        @pointerenter="show" @pointerleave="hide" @focus="onFocus" @blur="hide" @click.stop="show" @keydown.esc="hide">{{ socialTime(value, now) }}</time>
    </template>
    <span :id="tooltipId" role="tooltip">{{ full }}</span>
  </n-tooltip>
</template>
