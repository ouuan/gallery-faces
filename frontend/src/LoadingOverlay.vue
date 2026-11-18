<script setup lang="ts">
import { NSpin } from "naive-ui";
withDefaults(defineProps<{ show: boolean; label?: string; center?: boolean; error?: boolean }>(), {
  label: "正在加载…",
});
</script>
<template>
  <div v-if="show" class="loading-overlay" :class="{ 'loading-overlay-center': center }" role="status" aria-live="polite">
    <span class="loading-overlay-label"><n-spin v-if="!error" :size="16" aria-hidden="true" />{{ label }}</span>
  </div>
</template>
<style scoped>
.loading-overlay { position: absolute; inset: 8px 8px auto auto; z-index: 2; max-width: calc(100% - 16px); pointer-events: none; }
.loading-overlay-center { inset: 0; max-width: none; display: flex; align-items: center; justify-content: center; }
.loading-overlay-label { display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 6px; background: var(--panel); color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
</style>
