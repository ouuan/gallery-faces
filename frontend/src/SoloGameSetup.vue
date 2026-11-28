<script setup lang="ts">
import { NButton } from 'naive-ui';
import GameFilterEditor from './GameFilterEditor.vue';
import GameRoundLimit from './GameRoundLimit.vue';
import { rangeError } from './date-range';
import type { Filter } from './filters';

const filter = defineModel<Filter>({ required: true });
const roundLimit = defineModel<number>('roundLimit', { required: true });
defineProps<{ face?: boolean }>();
defineEmits<{ start: [] }>();
</script>

<template>
  <form class="solo-setup" aria-label="开局设置" @submit.prevent="!rangeError(filter.start, filter.end) && $emit('start')">
    <fieldset class="play-settings"><legend>玩法设置</legend>
      <GameRoundLimit v-model="roundLimit" />
      <slot />
    </fieldset>
    <GameFilterEditor v-model="filter" :face="face" />
    <n-button type="primary" attr-type="submit" :disabled="!!rangeError(filter.start, filter.end)">开始游戏</n-button>
  </form>
</template>

<style scoped>
.solo-setup { display: grid; gap: 16px; margin-top: 16px; }
.play-settings { display: grid; align-content: start; gap: 12px; margin: 0; padding: 0; border: 0; min-width: 0; }
.play-settings legend { padding: 0; margin-bottom: 8px; font-size: 16px; font-weight: 700; }
.solo-setup > button { justify-self: start; min-width: 8rem; }
@media (min-width: 760px) {
  .solo-setup { grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); grid-template-rows: auto auto 1fr; gap: 20px 48px; align-items: start; border-top: 1px solid var(--line); padding-top: 20px; }
  .solo-setup > .game-filters { grid-column: 2; grid-row: 1 / 4; border: 0; }
  .solo-setup :deep(.filter-toggle) { min-height: 44px; margin-top: -10px; }
}
@media (max-width: 599px) { .solo-setup > button { justify-self: stretch; } }
</style>
