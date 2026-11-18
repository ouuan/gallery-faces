<script setup lang="ts">
import LocalDateTime from "./LocalDateTime.vue";
import { computed, ref } from "vue";
import {
  NCheckbox,
  NSelect,
  NInput,
  NButton,
  NRadioGroup,
  NRadioButton,
} from "naive-ui";
import { useLibrary } from "./store";
import { hasFilters, type Filter } from "./filters";
import { platformLabel } from "./api";
import DateRangeHint from "./DateRangeHint.vue";
import PeopleMultiSelect from "./PeopleMultiSelect.vue";
const props = defineProps<{ modelValue: Filter; hideNoFaces?: boolean }>(),
  emit = defineEmits(["update:modelValue", "clear"]);
const store = useLibrary();
const publisherPlatform = ref("x"),
  publisherName = ref("");
function addPublisher() {
  const username = publisherName.value.trim().replace(/^@/, "");
  if (!username) return;
  const linked = store.people.find((p) =>
    p.accounts.some(
      (a) =>
        a.platform === publisherPlatform.value &&
        a.username.toLowerCase() === username.toLowerCase(),
    ),
  );
  set("publishers", [
    ...new Set([
      ...props.modelValue.publishers,
      linked ? `person:${linked.id}` : publisherPlatform.value + ":" + username,
    ]),
  ]);
  publisherName.value = "";
}
const personValues = computed(() =>
  props.modelValue.people.map((id) => `person:${id}`),
);
function selectPeople(values: string[]) {
  set("people", values.map((value) => Number(value.slice(7))));
}
function set(key: keyof Filter, value: any) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}
const publisherPeople = computed(() =>
  store.people.filter(
    (person) =>
      person.accounts.length ||
      props.modelValue.publishers.includes(`person:${person.id}`),
  ),
);
const publisherExtraOptions = computed(() => {
  const available = new Set(
    publisherPeople.value.map((person) => `person:${person.id}`),
  );
  return props.modelValue.publishers
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
  <div class="filters">
    <div class="section-heading">
      <h2>筛选照片</h2>
      <button
        v-if="hasFilters(modelValue)"
        class="text-button filter-clear"
        @click="emit('clear')"
      >清空</button>
    </div>
    <fieldset>
      <legend>照片中的人物</legend>
      <p v-if="!store.people.length" class="muted">尚未添加人物</p>
      <people-multi-select
        v-else
        class="people-cascader"
        aria-label="照片中的人物"
        :people="store.people"
        :groups="store.groups"
        :model-value="personValues"
        placeholder="选择分组或搜索人物"
        @update:model-value="selectPeople"
      />
      <p v-if="modelValue.people.length" class="hint">
        已选 {{ modelValue.people.length }} 位人物
      </p>
      <n-radio-group
        aria-label="人物匹配方式"
        v-if="modelValue.people.length > 1"
        :value="modelValue.match"
        @update:value="set('match', $event)"
        ><n-radio-button value="any">任一人物</n-radio-button
        ><n-radio-button value="all">全部同框</n-radio-button></n-radio-group
      >
    </fieldset>
    <fieldset>
      <legend>发布者</legend>
      <people-multi-select
        class="publisher-cascader"
        aria-label="发布者"
        :people="publisherPeople"
        :groups="store.groups"
        :model-value="modelValue.publishers"
        :extra-options="publisherExtraOptions"
        placeholder="选择分组或搜索发布者"
        @update:model-value="set('publishers', $event)"
      >
        <template #empty>暂无关联账号的人物，可输入用户名添加发布者</template>
        <template #not-found>没有匹配的发布者</template>
      </people-multi-select>
      <p class="hint">匹配所选人物在所有平台的关联账号</p>
      <div class="publisher-entry">
        <n-select
          v-model:value="publisherPlatform"
          aria-label="发布平台"
          :options="[
            { label: 'X / Twitter', value: 'x' },
            { label: 'Instagram', value: 'instagram' },
          ]"
        /><n-input
          v-model:value="publisherName"
          aria-label="发布者用户名"
          placeholder="输入用户名"
          @keydown.enter.prevent="addPublisher"
        /><n-button :disabled="!publisherName.trim()" @click="addPublisher"
          >添加发布者</n-button
        >
      </div>
    </fieldset>
    <fieldset>
      <legend>发布日期</legend>
      <label class="field-label date-field"
        >从<LocalDateTime aria-label="开始时间" :model-value="modelValue.start" @update:model-value="set('start', $event)" /></label
      ><label class="field-label date-field"
        >至<LocalDateTime aria-label="结束时间" :model-value="modelValue.end" @update:model-value="set('end', $event)" /></label>
      <DateRangeHint :start="modelValue.start" :end="modelValue.end" />
    </fieldset>
    <n-checkbox
      v-if="!hideNoFaces"
      :checked="modelValue.include_no_faces"
      @update:checked="set('include_no_faces', $event)"
      >包含无人脸图片</n-checkbox
    >
  </div>
</template>
