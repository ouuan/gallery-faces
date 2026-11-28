<script setup lang="ts">
import { NInputNumber, NRadioButton, NRadioGroup, NSwitch } from 'naive-ui';
import type { FaceDisplay } from './face-grid';
const display = defineModel<FaceDisplay>({ required: true });
</script>

<template>
  <div class="display-mode" role="group" aria-label="题图设置">
    <div class="mode-row"><span>显示方式</span>
      <n-radio-group :value="display.grid ? 'grid' : 'direct'" name="face-display" role="radiogroup" aria-label="显示方式"
        @update:value="mode => display = { ...display, grid: mode === 'grid' }">
        <n-radio-button value="direct">直接显示</n-radio-button>
        <n-radio-button value="grid">逐格显示</n-radio-button>
      </n-radio-group>
    </div>
    <div v-if="display.grid" class="grid-settings">
      <label>每边格数<n-input-number :value="display.grid_size" :min="2" :max="16" :precision="0" @update:value="value => display = { ...display, grid_size: value ?? 5 }" /></label>
      <label>每格间隔（秒）<n-input-number :value="display.grid_seconds" :min="0.1" :max="60" :step="0.1" @update:value="value => display = { ...display, grid_seconds: value ?? 0.5 }" /></label>
    </div>
    <label class="mode-row crop-row" @click.self="display = { ...display, cropped: !display.cropped }">仅截取人脸<n-switch aria-label="仅截取人脸" :value="display.cropped" @update:value="cropped => display = { ...display, cropped }" /></label>
  </div>
</template>

<style scoped>
.display-mode { display: grid; min-width: 0; gap: 4px; }
.mode-row { display: grid; grid-template-columns: 5em minmax(0, 1fr); align-items: center; justify-items: start; gap: 12px; }
.crop-row { min-height: 44px; width: fit-content; cursor: pointer; }
.grid-settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 8rem), 1fr)); gap: 12px; max-width: 24rem; padding-block: 8px; }
.grid-settings label { display: grid; gap: 4px; }
</style>
