<script setup lang="ts">
import { computed, ref } from 'vue';
import { NButton, NDropdown } from 'naive-ui';
import MoreMenuButton from './MoreMenuButton.vue';

type Action = 'backfill' | 'interval' | 'hashtags' | 'scope' | 'delete';
const props = defineProps<{ batch?: boolean; disabled: boolean }>();
const emit = defineEmits<{ select: [action: Action] }>();
const shown = ref(false);

function option(key: Action, label: string) {
  return { key, label, props: {
    role: 'menuitem',
    style: key === 'delete' ? { color: 'var(--error)' } : undefined,
  } };
}
const actions = computed(() => [
  option('backfill', '补齐'),
  option('interval', '修改间隔'),
  ...(props.batch ? [] : [option('hashtags', '修改标签')]),
  option('scope', '修改抓取范围'),
  option('delete', '删除'),
]);
const options = computed(() => actions.value.flatMap(action => action.key === 'delete'
  ? [{ type: 'divider' as const, key: 'divider' }, action] : [action]));
</script>

<template>
  <template v-if="batch">
    <n-button v-for="action in actions" :key="action.key" class="batch-direct" :disabled="disabled"
      :type="action.key === 'delete' ? 'error' : 'default'" :ghost="action.key === 'delete'" @click="emit('select', action.key)">{{ action.label }}</n-button>
  </template>
  <span class="more-anchor" :class="{ 'batch-overflow': batch }">
    <n-dropdown v-model:show="shown" trigger="click" placement="bottom-end" :disabled="disabled" :to="batch ? false : undefined"
      :options="options" :menu-props="() => ({ role: 'menu' })" @select="action => emit('select', action)">
      <MoreMenuButton :disabled="disabled" :aria-expanded="shown" @keydown.tab="shown = false" />
    </n-dropdown>
  </span>
</template>

<style scoped>
.more-anchor { display: inline-flex; }
.batch-direct { display: none; }
@container monitors (min-width: 43rem) {
  .batch-direct { display: inline-flex; }
  .batch-overflow { display: none; }
}
</style>
