<script setup lang="ts">
import { NInputNumber, NRadioButton, NRadioGroup } from 'naive-ui';
import type { FaceDisplay } from './face-grid';
const display = defineModel<FaceDisplay>({ required: true });
</script>

<template>
  <fieldset class="display-mode"><legend>题图显示</legend>
    <n-radio-group :value="display.grid ? 'grid' : display.cropped ? 'crop' : 'full'" name="face-display" role="radiogroup" aria-label="题图显示"
      @update:value="mode => display = { ...display, grid: mode === 'grid', cropped: mode === 'crop' }">
      <n-radio-button value="full">显示全图</n-radio-button>
      <n-radio-button value="crop">截取人脸</n-radio-button>
      <n-radio-button value="grid">逐格显示</n-radio-button>
    </n-radio-group>
    <div v-if="display.grid" class="grid-settings">
      <label>每边格数<n-input-number :value="display.grid_size" :min="2" :max="16" :precision="0" @update:value="value => display = { ...display, grid_size: value ?? 5 }" /></label>
      <label>每格间隔（秒）<n-input-number :value="display.grid_seconds" :min="0.1" :max="60" :step="0.1" @update:value="value => display = { ...display, grid_seconds: value ?? 0.5 }" /></label>
    </div>
  </fieldset>
</template>

<style scoped>
.display-mode { margin: 0; padding: 0; border: 0; }
.grid-settings { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; max-width: 24rem; }
.grid-settings label { display: grid; gap: 4px; }
legend { margin-bottom: 8px; font-weight: 600; }
</style>
