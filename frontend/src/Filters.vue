<script setup lang="ts">
import { computed, ref } from "vue";
import {
  NCheckbox,
  NSelect,
  NInput,
  NButton,
  NCascader,
  NRadioGroup,
  NRadioButton,
} from "naive-ui";
import { useLibrary } from "./store";
import type { Filter } from "./filters";
import { platformLabel } from "./api";
import { peopleOptions, peopleKeys, updatePeople } from "./people-cascader";
const props = defineProps<{ modelValue: Filter }>(),
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
const personOptions = computed(() => peopleOptions(store.people, store.groups));
const personKeys = computed(() =>
  peopleKeys(props.modelValue.people, personOptions.value),
);
function selectPeople(keys: (string | number)[] | null) {
  set(
    "people",
    updatePeople(keys, props.modelValue.people, personOptions.value),
  );
}
function set(key: keyof Filter, value: any) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}
const publisherOptions = computed(() => {
  const options = store.people
    .filter(
      (p) =>
        p.accounts.length ||
        props.modelValue.publishers.includes(`person:${p.id}`),
    )
    .map((p) => ({ label: p.name, value: `person:${p.id}` }));
  for (const value of props.modelValue.publishers) {
    if (options.some((option) => option.value === value)) continue;
    const [platform, username] = value.split(":", 2);
    options.push({
      value,
      label:
        platform === "person"
          ? "已删除人物"
          : `${platformLabel(platform)} · @${username}`,
    });
  }
  return options;
});
</script>
<template>
  <div class="filters">
    <div class="section-heading">
      <h2>筛选照片</h2>
      <button class="text-button" @click="emit('clear')">清空</button>
    </div>
    <fieldset>
      <legend>照片中的人物</legend>
      <p v-if="!store.people.length" class="muted">尚未添加人物</p>
      <n-cascader
        v-else
        class="people-cascader"
        aria-label="照片中的人物"
        multiple
        filterable
        clearable
        check-strategy="parent"
        expand-trigger="click"
        :options="personOptions"
        :value="personKeys"
        placeholder="选择分组或搜索人物"
        :max-tag-count="2"
        :menu-props="{ class: 'people-cascader-menu' }"
        :filter-menu-props="{ class: 'people-cascader-search' }"
        :theme-overrides="{
          columnWidth: 'min(180px, calc((100vw - 48px) / 2))',
          optionHeight: '44px',
        }"
        @update:value="selectPeople"
      >
        <template #empty>暂无人物</template>
        <template #not-found>没有匹配的人物</template>
      </n-cascader>
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
      <n-select
        aria-label="发布者"
        multiple
        filterable
        :value="modelValue.publishers"
        :options="publisherOptions"
        placeholder="按人物选择发布者"
        @update:value="set('publishers', $event)"
      />
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
        >从<input
          aria-label="开始日期"
          type="date"
          :value="modelValue.start"
          @input="
            set('start', ($event.target as HTMLInputElement).value)
          " /></label
      ><label class="field-label date-field"
        >至<input
          aria-label="结束日期"
          type="date"
          :value="modelValue.end"
          @input="set('end', ($event.target as HTMLInputElement).value)"
      /></label>
    </fieldset>
    <n-checkbox
      :checked="modelValue.include_no_faces"
      @update:checked="set('include_no_faces', $event)"
      >包含无人脸图片</n-checkbox
    >
  </div>
</template>
