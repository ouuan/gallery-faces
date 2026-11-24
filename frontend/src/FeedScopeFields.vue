<script setup lang="ts">
import { computed } from 'vue';
import { NCheckbox, NFlex, NFormItem } from 'naive-ui';
import { platformLabel } from './api';
import type { FeedScope } from './feed-scope';

const props = defineProps<{ platform: string; singleImport?: boolean; disabled?: boolean }>();
const scope = defineModel<FeedScope>({ required: true });
const labels = { retweets: '转推', quoted: '引用', stories: '快拍', tagged: 'tagged', reposts: '转发' };
const keys = computed<(keyof FeedScope)[]>(() => props.platform === 'x' ? ['retweets', 'quoted'] : props.singleImport ? ['stories', 'tagged', 'reposts'] : ['stories', 'tagged']);
</script>

<template>
  <n-form-item :label="platformLabel(platform)" label-placement="left" :label-style="{ alignSelf: 'center' }" :show-feedback="false" role="group" :aria-label="`${platformLabel(platform)} 抓取范围`">
    <n-flex size="small" align="center">
      <n-checkbox v-for="key in keys" :key="key" :checked="scope[key]" :disabled="disabled" :aria-disabled="disabled" @update:checked="scope = { ...scope, [key]: $event }">{{ labels[key] }}</n-checkbox>
    </n-flex>
  </n-form-item>
</template>

<style scoped>
@media (pointer: coarse) {
  .n-checkbox { min-height: 44px; align-items: center; }
}
</style>
