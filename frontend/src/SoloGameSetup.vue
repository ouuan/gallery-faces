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
    <GameRoundLimit v-model="roundLimit" />
    <slot />
    <GameFilterEditor v-model="filter" :face="face" />
    <n-button type="primary" attr-type="submit" :disabled="!!rangeError(filter.start, filter.end)">开始游戏</n-button>
  </form>
</template>

<style scoped>
.solo-setup { display: grid; gap: 20px; margin-top: 16px; }
.solo-setup > button { justify-self: start; min-width: 8rem; }
@media (max-width: 599px) { .solo-setup > button { justify-self: stretch; } }
</style>
