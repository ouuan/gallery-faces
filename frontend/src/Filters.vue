<script setup lang="ts">
import { t, ja } from "./locale";
import LocalDateTime from "./LocalDateTime.vue";
import { computed, ref } from "vue";
import {
  NCheckbox,
  NSelect,
  NInput,
  NButton,
  NRadioGroup,
  NRadioButton,
  NRadio,
} from "naive-ui";
import { useLibrary } from "./store";
import { hasFilters, type Filter } from "./filters";
import DateRangeHint from "./DateRangeHint.vue";
import PublisherSelect from "./PublisherSelect.vue";
import PeopleMultiSelect from "./PeopleMultiSelect.vue";
const props = defineProps<{ modelValue: Filter; hideNoFaces?: boolean }>(),
  emit = defineEmits(["update:modelValue", "clear"]);
const store = useLibrary();
const publisherPlatform = ref("x"),
  publisherName = ref("");
const filterPeople = computed(() =>
  store.people.filter((person) => person.reference_count > 0),
);
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
</script>
<template>
  <div class="filters" :class="{ 'filters-ja': ja }">
    <div class="section-heading">
      <h2>{{ t("筛选照片") }}</h2>
      <button
        v-if="hasFilters(modelValue)"
        class="text-button filter-clear"
        @click="emit('clear')"
      >{{ t("清空") }}</button>
    </div>
    <fieldset>
      <legend>{{ t("照片中的人物") }}</legend>
      <p v-if="!store.people.length" class="muted">{{ t("尚未添加人物") }}</p>
      <people-multi-select
        v-else
        class="people-cascader"
        :aria-label="t('照片中的人物')"
        :people="filterPeople"
        :groups="store.groups"
        :model-value="personValues"
        :placeholder="t('选择分组或搜索人物')"
        @update:model-value="selectPeople"
      />
      <p v-if="modelValue.people.length" class="hint">
        {{ ja ? `${modelValue.people.length}人を選択中` : `已选 ${modelValue.people.length} 位人物` }}
      </p>
      <n-radio-group
        :class="{ 'person-match-ja': ja }"
        :aria-label="t('人物匹配方式')"
        v-if="modelValue.people.length > 1"
        :value="modelValue.match"
        @update:value="set('match', $event)"
        ><template v-if="ja">
          <n-radio value="any">{{ t("任一人物") }}</n-radio>
          <n-radio value="all">{{ t("全部同框") }}</n-radio>
        </template><template v-else>
          <n-radio-button value="any">{{ t("任一人物") }}</n-radio-button>
          <n-radio-button value="all">{{ t("全部同框") }}</n-radio-button>
        </template></n-radio-group
      >
    </fieldset>
    <fieldset>
      <legend>{{ t("发布者") }}</legend>
      <PublisherSelect :model-value="modelValue.publishers" @update:model-value="set('publishers', $event)" />
      <p class="hint">{{ t("匹配所选人物在所有平台的关联账号") }}</p>
      <div class="publisher-entry">
        <n-select
          v-model:value="publisherPlatform"
          :aria-label="t('发布平台')"
          :options="[
            { label: 'X / Twitter', value: 'x' },
            { label: 'Instagram', value: 'instagram' },
          ]"
        /><n-input
          v-model:value="publisherName"
          :aria-label="t('发布者用户名')"
          :placeholder="t('输入用户名')"
          @keydown.enter.prevent="addPublisher"
        /><n-button :disabled="!publisherName.trim()" @click="addPublisher"
          >{{ t("添加发布者") }}</n-button
        >
      </div>
    </fieldset>
    <fieldset>
      <legend>{{ t("发布日期") }}</legend>
      <label class="field-label date-field"
        >{{ t("从") }}<LocalDateTime :aria-label="t('开始时间')" :model-value="modelValue.start" @update:model-value="set('start', $event)" /></label
      ><label class="field-label date-field"
        >{{ t("至") }}<LocalDateTime :aria-label="t('结束时间')" :model-value="modelValue.end" @update:model-value="set('end', $event)" /></label>
      <DateRangeHint :start="modelValue.start" :end="modelValue.end" />
    </fieldset>
    <n-checkbox
      v-if="!hideNoFaces"
      :checked="modelValue.include_no_faces"
      @update:checked="set('include_no_faces', $event)"
      >{{ t("包含无人脸图片") }}</n-checkbox
    >
  </div>
</template>
<style scoped>
.filters-ja > .section-heading { min-height: 44px; gap: 8px; }
.filters-ja .filter-clear { position: static; transform: none; flex-shrink: 0; }
.filters-ja .field-label.date-field { grid-template-columns: 2em minmax(0, 1fr); gap: 8px; }
.filters-ja .hint { overflow-wrap: anywhere; }
.person-match-ja { display: flex; flex-direction: column; }
.person-match-ja :deep(.n-radio) { min-height: 44px; align-items: center; margin: 0; }
.person-match-ja :deep(.n-radio__label) { white-space: normal; }
</style>
