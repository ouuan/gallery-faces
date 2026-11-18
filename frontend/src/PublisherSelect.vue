<script setup lang="ts">
import { computed } from "vue";
import { useLibrary } from "./store";
import { platformLabel } from "./api";
import PeopleMultiSelect from "./PeopleMultiSelect.vue";
const props = defineProps<{ modelValue: string[] }>();
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const store = useLibrary();
const publisherPeople = computed(() =>
  store.people.filter(
    (person) =>
      person.accounts.length ||
      props.modelValue.includes(`person:${person.id}`),
  ),
);
const publisherExtraOptions = computed(() => {
  const available = new Set(
    publisherPeople.value.map((person) => `person:${person.id}`),
  );
  return props.modelValue
    .filter((value) => !available.has(value))
    .map((value) => {
      const [platform, username] = value.split(":", 2);
      return {
        value,
        label:
          platform === "person"
            ? "已删除人物"
            : `${platformLabel(platform)} · @${username}`,
      };
    });
});
</script>
<template>
  <PeopleMultiSelect
    class="publisher-cascader"
    aria-label="发布者"
    :people="publisherPeople"
    :groups="store.groups"
    :model-value="modelValue"
    :extra-options="publisherExtraOptions"
    placeholder="选择分组或搜索发布者"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #empty>暂无关联账号的人物</template>
    <template #not-found>没有匹配的发布者</template>
  </PeopleMultiSelect>
</template>
