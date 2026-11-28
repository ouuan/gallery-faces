<script setup lang="ts">
import { t } from "./locale";
import { cloneVNode, computed, type VNode } from "vue";
import { NCascader, type CascaderOption } from "naive-ui";
import type { Person } from "./api";
import { peopleOptions, pickerIndex } from "./people-cascader";

const props = withDefaults(defineProps<{
  modelValue: string[];
  people: Person[];
  groups: { id: number; name: string }[];
  extraGroups?: { label: string; value: string; children: { label: string; value: string }[] }[];
}>(), { extraGroups: () => [] });
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const groupedOptions = computed(() => peopleOptions(props.people, props.groups));
const options = computed(() => [...groupedOptions.value, ...props.extraGroups]);
const index = computed(() => pickerIndex(options.value));
const selected = computed(() => new Set(props.modelValue));
const value = computed(() => index.value.tagKeys(selected.value));
function checkbox({ option, node }: { option: CascaderOption; node: VNode | null }) {
  if (!node) return null;
  const members = index.value.members.get(String(option.value))!;
  const checked = members.filter(id => selected.value.has(id)).length;
  return cloneVNode(node, {
    checked: checked === members.length,
    indeterminate: checked > 0 && checked < members.length,
  });
}
function toggle(members: string[], retained: Set<string>) {
  const next = new Set(selected.value);
  const remove = members.every(id => next.has(id));
  for (const id of members) {
    if (remove && retained.has(id)) continue;
    if (remove) next.delete(id);
    else next.add(id);
  }
  emit("update:modelValue", [...next]);
}
function update(keys: (string | number)[] | null) {
  if (!keys?.length) return emit("update:modelValue", []);
  const changed = keys.find(key => !value.value.includes(String(key)))
    ?? value.value.find(key => !keys.includes(key));
  if (changed != null) {
    const retained = value.value.includes(String(changed))
      ? keys.flatMap(key => index.value.members.get(String(key))!) : [];
    toggle(index.value.members.get(String(changed))!, new Set(retained));
  }
}
</script>
<template>
  <n-cascader
    multiple
    filterable
    clearable
    check-strategy="parent"
    :cascade="false"
    :filter="index.filter"
    :render-prefix="checkbox"
    :show-path="false"
    :virtual-scroll="false"
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
