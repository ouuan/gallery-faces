<script lang="ts">
export const splitHashtags = (value: string) => value.split(/[\s,，、]+/u).filter(Boolean);
export const formatHashtags = (tags: string[]) => tags.map(tag => `#${tag}`).join(" ");
</script>
<script setup lang="ts">
import { NInput } from "naive-ui";
const value = defineModel<string>({ required: true });
defineProps<{ disabled?: boolean }>();
</script>
<template>
  <label class="field-label">话题标签（匹配任一）
    <n-input v-model:value="value" :disabled="disabled" clearable placeholder="#摄影 #现场，留空不限" />
  </label>
</template>
