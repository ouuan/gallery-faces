<script setup lang="ts">
import { t, ja } from "./locale";
import LocalDateTime from "./LocalDateTime.vue";
import { computed } from "vue";
import {
  NCheckbox,
  NRadioGroup,
  NRadioButton,
} from "naive-ui";
import { useLibrary } from "./store";
import { CalendarDays, Rss, Shuffle } from "@lucide/vue";
import { filterOnlyQuery, feedHref, hasFilters, type Filter } from "./filters";
import DateRangeHint from "./DateRangeHint.vue";
import PublisherSelect from "./PublisherSelect.vue";
import PeopleMultiSelect from "./PeopleMultiSelect.vue";
const props = defineProps<{ modelValue: Filter; hideNoFaces?: boolean; showGalleryLinks?: boolean; contained?: boolean }>(),
  emit = defineEmits(["update:modelValue", "clear"]);
const store = useLibrary();
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
        :to="contained ? false : undefined"
        :aria-label="t('照片中的人物')"
        :people="store.people"
        :groups="store.groups"
        :model-value="personValues"
        :placeholder="t('选择分组或搜索人物')"
        @update:model-value="selectPeople"
      />
      <p v-if="modelValue.people.length" class="hint">
        {{ ja ? `${modelValue.people.length}人を選択中` : `已选 ${modelValue.people.length} 位人物` }}
      </p>
      <div v-if="modelValue.people.length" class="people-modes">
        <n-radio-group v-if="modelValue.people.length > 1" role="radiogroup"
          :aria-label="t('人物匹配方式')" :value="modelValue.match" @update:value="set('match', $event)">
          <n-radio-button value="any">{{ t("任一入镜") }}</n-radio-button>
          <n-radio-button value="all">{{ t("全部同框") }}</n-radio-button>
        </n-radio-group>
        <n-radio-group role="radiogroup" :aria-label="t('是否包含其他人物')"
          :value="modelValue.onlySelected" @update:value="set('onlySelected', $event)">
          <n-radio-button :value="true">{{ t("仅限所选") }}</n-radio-button>
          <n-radio-button :value="false">{{ t("可含他人") }}</n-radio-button>
        </n-radio-group>
      </div>
    </fieldset>
    <fieldset>
      <legend>{{ t("发布者") }}</legend>
      <PublisherSelect include-other :to="contained ? false : undefined" :model-value="modelValue.publishers" @update:model-value="set('publishers', $event)" />
      <p class="hint">{{ t("匹配所选人物的关联账号或其他发布者账号") }}</p>
    </fieldset>
    <fieldset>
      <legend>{{ t("发布日期") }}</legend>
      <label class="field-label date-field"
        >{{ t("从") }}<LocalDateTime :contained="contained" :aria-label="t('开始时间')" :model-value="modelValue.start" @update:model-value="set('start', $event)" /></label
      ><label class="field-label date-field"
        >{{ t("至") }}<LocalDateTime :contained="contained" :aria-label="t('结束时间')" :model-value="modelValue.end" @update:model-value="set('end', $event)" /></label>
      <DateRangeHint :start="modelValue.start" :end="modelValue.end" />
    </fieldset>
    <n-checkbox
      v-if="!hideNoFaces"
      :checked="modelValue.include_no_faces"
      @update:checked="set('include_no_faces', $event)"
      >{{ t("包含无人脸图片") }}</n-checkbox
    >
    <div v-if="showGalleryLinks" class="gallery-links">
      <router-link class="icon-link" :to="{ path: '/daily', query: filterOnlyQuery(modelValue) }" title="每日一图" aria-label="每日一图">
        <CalendarDays :size="18" aria-hidden="true" />
      </router-link>
      <router-link class="icon-link" :to="{ path: '/random', query: filterOnlyQuery(modelValue) }" title="随机图片" aria-label="随机图片">
        <Shuffle :size="18" aria-hidden="true" />
      </router-link>
      <a class="icon-link" :href="feedHref(modelValue)" title="订阅图库 RSS" aria-label="订阅图库 RSS"><Rss :size="18" aria-hidden="true" /></a></div>
  </div>
</template>
<style scoped>
.gallery-links { display: flex; align-items: center; justify-content: center; border-top: 1px solid var(--line); padding-top: 8px; }
.filters-ja > .section-heading { min-height: 44px; gap: 8px; }
.filters-ja .filter-clear { position: static; transform: none; flex-shrink: 0; }
.filters-ja .field-label.date-field { grid-template-columns: 2em minmax(0, 1fr); gap: 8px; }
.filters-ja .hint { overflow-wrap: anywhere; }
.people-modes { display: grid; gap: 8px; }
.people-modes :deep(.n-radio-group) { display: flex; }
.people-modes :deep(.n-radio-button) { flex: 1; padding-inline: 4px; text-align: center; white-space: nowrap; }
</style>
