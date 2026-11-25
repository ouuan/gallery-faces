<script setup lang="ts">
import { computed, useAttrs } from "vue";
import { NDatePicker } from "naive-ui";
import { validInstant } from "./date-range";
defineOptions({ inheritAttrs: false });
const vInputLabel = {
  mounted(el: HTMLElement, binding: { value: unknown }) {
    if (binding.value) el.querySelector("input")?.setAttribute("aria-label", String(binding.value));
  },
  updated(el: HTMLElement, binding: { value: unknown }) {
    if (binding.value) el.querySelector("input")?.setAttribute("aria-label", String(binding.value));
  },
};
const attrs = useAttrs();
const props = defineProps<{ modelValue?: string | null; disabled?: boolean; contained?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const value = computed(() => props.modelValue && validInstant(props.modelValue) ? Date.parse(props.modelValue) : null);
</script>
<template>
  <n-date-picker @keydown.enter.prevent type="datetime" v-input-label="attrs['aria-label']" :value="value" clearable :disabled="disabled" format="yyyy-MM-dd HH:mm:ss"
    :to="contained ? false : undefined"
    :theme-overrides="contained ? { itemCellWidth: 'min(38px, calc((100cqi - 24px) / 7))' } : undefined"
    @update:value="emit('update:modelValue', $event == null ? '' : new Date($event).toISOString().replace('.000Z', 'Z'))" />
</template>
