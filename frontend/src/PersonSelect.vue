<script setup lang="ts">
import { computed } from "vue";
import { NCascader } from "naive-ui";
import { useLibrary } from "./store";
import { peopleOptions, peopleKeys } from "./people-cascader";

const props = defineProps<{
  modelValue: number | null;
  disabled?: boolean;
  accessibleLabel: string;
}>();
const emit = defineEmits<{ "update:modelValue": [value: number | null] }>();
const store = useLibrary();
const options = computed(() => peopleOptions(store.people, store.groups));
const value = computed(() =>
  props.modelValue == null
    ? null
    : peopleKeys([props.modelValue], options.value)[0] ?? null,
);
function update(key: string | number | (string | number)[] | null) {
  const person = options.value
    .flatMap((group) => group.children)
    .find((option) => option.value === key);
  emit("update:modelValue", person?.personId ?? null);
}
</script>
<template>
  <n-cascader
    :value="value"
    :options="options"
    :disabled="disabled"
    :aria-label="accessibleLabel"
    clearable
    filterable
    check-strategy="child"
    expand-trigger="click"
    :show-path="false"
    :virtual-scroll="false"
    placeholder="未知人物"
    :menu-props="{ class: 'people-cascader-menu' }"
    :filter-menu-props="{ class: 'people-cascader-search' }"
    :theme-overrides="{
      columnWidth: 'min(180px, calc((100vw - 48px) / 2))',
      optionHeight: '44px',
    }"
    @update:value="update"
  >
    <template #empty>暂无人物</template>
    <template #not-found>没有匹配的人物</template>
  </n-cascader>
</template>
