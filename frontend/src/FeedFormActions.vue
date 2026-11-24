<script setup lang="ts">
import { NButton, NFlex } from 'naive-ui';
defineProps<{ busy: boolean; disabled: boolean }>();
</script>

<template>
  <n-flex>
    <n-button class="stable-loading-button" type="primary" attr-type="submit" :disabled="busy || disabled" :loading="busy"><slot /></n-button>
    <n-button attr-type="reset" :disabled="busy">重置</n-button>
  </n-flex>
</template>
