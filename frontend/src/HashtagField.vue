<script lang="ts">
export const formatHashtags = (tags: string[]) => tags.map(tag => `#${tag}`).join(" ");
</script>
<script setup lang="ts">
import { NButton, NDynamicTags } from "naive-ui";
const value = defineModel<string[]>({ required: true });
defineProps<{ disabled?: boolean }>();
function updateTags(tags: string[]) {
  value.value = [...new Set(tags.flatMap(tag => tag.split(/[\s,，、]+/u)).map(tag => tag.replace(/^[#＃]/u, '')).filter(Boolean))];
}
function preventSubmit(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.isComposing) event.preventDefault();
}
</script>
<template>
  <fieldset class="scope-field hashtag-field">
    <legend>话题标签（匹配任一）</legend>
    <n-dynamic-tags :value="value" :disabled="disabled" :input-props="{ inputProps: { 'aria-label': '话题标签' }, placeholder: '#摄影', onKeydown: preventSubmit }" @update:value="updateTags">
      <template #trigger="{ activate, disabled: triggerDisabled }">
        <n-button dashed size="small" :disabled="triggerDisabled" @click="activate">添加标签</n-button>
      </template>
    </n-dynamic-tags>
  </fieldset>
</template>

<style scoped>
.hashtag-field { margin-block: 16px; }
</style>
