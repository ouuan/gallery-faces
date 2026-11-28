<script setup lang="ts">
import { ref } from 'vue';
import { NInputNumber, NRadioButton, NRadioGroup } from 'naive-ui';

const limit = defineModel<number>({ required: true });
const fixed = ref(limit.value || 25);
function changeMode(mode: string) {
  if (limit.value) fixed.value = limit.value;
  limit.value = mode === 'fixed' ? fixed.value : 0;
}
</script>

<template>
  <div class="round-limit"><span aria-hidden="true">游戏局数</span>
    <div class="controls">
      <n-radio-group :value="limit ? 'fixed' : 'endless'" name="round-mode" role="radiogroup" aria-label="游戏局数" @update:value="changeMode">
        <n-radio-button value="endless">无尽</n-radio-button>
        <n-radio-button value="fixed">固定局数</n-radio-button>
      </n-radio-group>
      <n-input-number v-if="limit" :value="limit" :min="1" :max="999" :precision="0" :input-props="{ 'aria-label': '题数' }" @update:value="value => limit = value ?? fixed">
        <template #suffix>题</template>
      </n-input-number>
    </div>
  </div>
</template>

<style scoped>
.round-limit { display: grid; grid-template-columns: 5em minmax(0, 1fr); align-items: baseline; gap: 12px; min-width: 0; }
.controls { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; }
.n-input-number { width: 8rem; }
</style>
