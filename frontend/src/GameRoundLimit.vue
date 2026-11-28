<script setup lang="ts">
import { ref } from 'vue';
import { NInputNumber, NRadioButton, NRadioGroup } from 'naive-ui';

const props = defineProps<{ limit: number; singleLife?: boolean; allowLife?: boolean }>();
const emit = defineEmits<{ change: [limit: number, singleLife: boolean] }>();
const fixed = ref(props.limit || 25);
function changeMode(mode: string) {
  if (props.limit) fixed.value = props.limit;
  emit('change', mode === 'fixed' ? fixed.value : 0, mode === 'life');
}
</script>

<template>
  <div class="round-limit"><span aria-hidden="true">游戏局数</span>
    <div class="controls">
      <n-radio-group :value="singleLife ? 'life' : limit ? 'fixed' : 'endless'" name="round-mode" role="radiogroup" aria-label="游戏局数" @update:value="changeMode">
        <n-radio-button value="fixed">固定局数</n-radio-button>
        <n-radio-button value="endless">无尽</n-radio-button>
        <n-radio-button v-if="allowLife" value="life">一命模式</n-radio-button>
      </n-radio-group>
      <n-input-number v-if="limit && !singleLife" :value="limit" :min="1" :max="999" :precision="0" :input-props="{ 'aria-label': '题数' }" @update:value="value => emit('change', value ?? fixed, false)">
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
