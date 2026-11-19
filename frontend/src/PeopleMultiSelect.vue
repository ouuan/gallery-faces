<script setup lang="ts">
import { t, ja } from "./locale";
import { computed } from "vue";
import { NCascader } from "naive-ui";
import type { Person } from "./api";
import { peopleOptions, peopleKeys, updatePeople } from "./people-cascader";

const props = withDefaults(defineProps<{
  // People use person:<id>; supplemental options keep their own values.
  modelValue: string[];
  people: Person[];
  groups: { id: number; name: string }[];
  extraOptions?: { label: string; value: string }[];
}>(), { extraOptions: () => [] });
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const groupedOptions = computed(() => peopleOptions(props.people, props.groups));
const options = computed(() => [...groupedOptions.value, ...props.extraOptions]);
const selectedIds = computed(() => {
  const available = new Set(props.people.map((person) => `person:${person.id}`));
  return props.modelValue
    .filter((value) => available.has(value))
    .map((value) => Number(value.slice(7)));
});
const value = computed(() => [
  ...peopleKeys(selectedIds.value, groupedOptions.value),
  ...props.extraOptions
    .filter((option) => props.modelValue.includes(option.value))
    .map((option) => option.value),
]);
function update(keys: (string | number)[] | null) {
  const selected = new Set(keys);
  emit("update:modelValue", [
    ...updatePeople(keys, selectedIds.value, groupedOptions.value)
      .map((id) => `person:${id}`),
    ...props.extraOptions
      .filter((option) => selected.has(option.value))
      .map((option) => option.value),
  ]);
}
</script>
<template>
  <n-cascader
    multiple
    filterable
    clearable
    check-strategy="parent"
    expand-trigger="click"
    :options="options"
    :value="value"
    :max-tag-count="2"
    :menu-props="{ class: 'people-cascader-menu' }"
    :filter-menu-props="{ class: 'people-cascader-search' }"
    :theme-overrides="{
      columnWidth: 'min(180px, calc((100vw - 48px) / 2))',
      optionHeight: '44px',
    }"
    @update:value="update"
  >
    <template #empty><slot name="empty">{{ t("暂无人物") }}</slot></template>
    <template #not-found><slot name="not-found">{{ t("没有匹配的人物") }}</slot></template>
  </n-cascader>
</template>
