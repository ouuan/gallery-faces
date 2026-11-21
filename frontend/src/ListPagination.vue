<script setup lang="ts">
import { ChevronLeft, ChevronRight } from "@lucide/vue";
import { NButton, NPagination } from "naive-ui";

defineProps<{ page: number; pageCount: number; disabled: boolean }>();
const emit = defineEmits<{ change: [page: number] }>();
</script>

<template>
  <n-pagination :page="page" :page-count="pageCount" :page-slot="5" :disabled="disabled"
    :show-quick-jump-dropdown="false" @update:page="$event !== page && emit('change', $event)">
    <template #prev>
      <n-button quaternary circle size="small" aria-label="上一页" :disabled="disabled || page <= 1">
        <template #icon><ChevronLeft /></template>
      </n-button>
    </template>
    <template #label="{ type, node, active }">
      <button type="button" class="page-number" :disabled="disabled" :aria-current="type === 'page' && active ? 'page' : undefined"
        :aria-label="type === 'page' ? `第 ${node} 页` : type === 'fast-forward' ? '向后跳页' : '向前跳页'">
        {{ type === 'page' ? node : '…' }}
      </button>
    </template>
    <template #next>
      <n-button quaternary circle size="small" aria-label="下一页" :disabled="disabled || page >= pageCount">
        <template #icon><ChevronRight /></template>
      </n-button>
    </template>
  </n-pagination>
</template>

<style scoped>
.page-number { width: 100%; height: 100%; padding: 0; border: 0; background: none; color: inherit; font: inherit; cursor: inherit; }
</style>
