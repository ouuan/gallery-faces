<script setup lang="ts">
import { NCheckbox } from 'naive-ui';

defineProps<{ count: number; total: number; label?: string }>();
defineEmits<{ toggle: [checked: boolean] }>();
</script>

<template>
  <div v-if="total" class="list-selection">
    <div class="selection-total">
      <n-checkbox :checked="count === total" :indeterminate="count > 0 && count < total" @update:checked="$emit('toggle', $event)">{{ label ?? '全选' }}</n-checkbox>
      <span v-if="count">已选 {{ count }} 项</span>
    </div>
    <div v-if="count" class="batch-actions" role="group" aria-label="批量操作"><slot /></div>
  </div>
</template>

<style scoped>
.list-selection, .selection-total, .batch-actions { display: flex; flex-wrap: wrap; align-items: center; }
.list-selection { justify-content: space-between; gap: 4px 12px; padding: 4px 12px; }
.selection-total { gap: 8px; }
.selection-total .n-checkbox { min-height: 44px; align-items: center; }
.selection-total span { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.batch-actions { gap: 8px 4px; }
</style>
