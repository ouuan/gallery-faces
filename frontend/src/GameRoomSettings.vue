<script setup lang="ts">
import { NInputNumber, NSwitch } from 'naive-ui';
import type { Settings } from './use-game-room';
const model = defineModel<Settings>({ required: true });
</script>
<template>
  <fieldset><legend>房间设置</legend>
    <label>每题答题时间（秒）<n-input-number aria-label="每题答题时间" :value="model.answer_seconds" :min="3" :max="300" @update:value="value => model = { ...model, answer_seconds: value ?? 15 }" /></label>
    <label>自动切题等待（秒，0 为关闭）<n-input-number aria-label="自动切题等待" :value="model.continue_seconds" :min="0" :max="300" @update:value="value => model = { ...model, continue_seconds: value ?? 0 }" /></label>
    <label class="display">题图显示 <span>显示全图 <n-switch aria-label="截取人脸" :value="model.cropped" @update:value="value => model = { ...model, cropped: value }" /> 截取人脸</span></label>
    <label class="display"><span><n-switch aria-label="一命模式" :value="model.single_life" @update:value="value => model = { ...model, single_life: value }" /> 一命模式</span></label>
  </fieldset>
</template>
<style scoped>
fieldset { display: grid; gap: 12px; border: 0; padding: 0; min-width: 0; margin: 6px 0; }
legend { font-weight: 600; margin-bottom: 8px; }
label { display: grid; gap: 4px; }
.display span { display: flex; align-items: center; gap: 8px; min-height: 44px; }
</style>
