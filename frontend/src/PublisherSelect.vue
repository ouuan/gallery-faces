<script setup lang="ts">
import { t } from "./locale";
import { computed } from "vue";
import { useLibrary } from "./store";
import { platformLabel } from "./api";
import PeopleMultiSelect from "./PeopleMultiSelect.vue";
const props = defineProps<{ modelValue: string[]; includeOther?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const store = useLibrary();
const publisherPeople = computed(() =>
  store.people.filter(
    (person) => person.accounts.length,
  ),
);
const linkedAccounts = computed(() => new Set(
  store.people.flatMap((person) => person.accounts.map((account) =>
    `${account.platform}:${account.username.toLowerCase()}`,
  )),
));
const publisherOtherGroups = computed(() => {
  if (!props.includeOther) return [];
  const options = new Map<string, { label: string; value: string }>();
  for (const candidate of store.publisherCandidates) {
    const value = `${candidate.platform}:${candidate.username}`;
    if (linkedAccounts.value.has(value.toLowerCase())) continue;
    options.set(value.toLowerCase(), {
      value,
      label: `${candidate.label || `@${candidate.username}`} · ${platformLabel(candidate.platform)}`,
    });
  }
  return options.size
    ? [{ label: t("其他"), value: "publisher:other", children: [...options.values()] }]
    : [];
});
</script>
<template>
  <PeopleMultiSelect
    class="publisher-cascader"
    :aria-label="t('发布者')"
    :people="publisherPeople"
    :groups="store.groups"
    :model-value="modelValue"
    :extra-groups="publisherOtherGroups"
    :placeholder="t('选择分组或搜索发布者')"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #empty>{{ t("暂无发布者") }}</template>
    <template #not-found>{{ t("没有匹配的发布者") }}</template>
  </PeopleMultiSelect>
</template>
