<script setup lang="ts">
import { NInputNumber, NRadioButton, NRadioGroup, NSwitch } from 'naive-ui';
import type { FaceDisplay } from './face-grid';
const display = defineModel<FaceDisplay>({ required: true });
</script>

<template>
  <fieldset class="display-mode"><legend>题图设置</legend>
    <label class="mode-row" @click.self="display = { ...display, cropped: !display.cropped }">只看人脸<n-switch aria-label="只看人脸" :value="display.cropped" @update:value="cropped => display = { ...display, cropped }" /></label>
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
  </fieldset>
</template>

<style scoped>
.display-mode { min-width: 0; margin: 0; padding: 0; border: 0; }
.mode-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; min-height: 44px; width: fit-content; }
.grid-settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr)); gap: 12px; margin-top: 8px; max-width: 24rem; }
.grid-settings label { display: grid; gap: 4px; }
legend { margin-bottom: 8px; font-weight: 600; }
</style>
