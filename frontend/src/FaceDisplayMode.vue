<script setup lang="ts">
import { NRadioButton, NRadioGroup } from 'naive-ui';
const cropped = defineModel<boolean>({ required: true });
</script>

<template>
  <fieldset class="display-mode"><legend>题图显示</legend>
    <n-radio-group v-model:value="cropped" name="face-display" role="radiogroup" aria-label="题图显示">
      <n-radio-button :value="false">显示全图</n-radio-button>
      <n-radio-button :value="true">截取人脸</n-radio-button>
    </n-radio-group>
  </fieldset>
</template>

<style scoped>
.display-mode { margin: 0; padding: 0; border: 0; }
legend { margin-bottom: 8px; font-weight: 600; }
</style>
