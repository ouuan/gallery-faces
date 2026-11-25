<script setup lang="ts">
import { Ellipsis } from '@lucide/vue';
import { NButton } from 'naive-ui';

withDefaults(defineProps<{ label?: string }>(), { label: '更多' });
</script>

<template>
  <n-button quaternary circle :aria-label="label" title="更多" aria-haspopup="menu">
    <template #icon><Ellipsis :size="20" aria-hidden="true" /></template>
  </n-button>
</template>
