<script setup lang="ts">
import { NCheckbox, NCheckboxGroup } from 'naive-ui';
import { platformLabel } from './api';
import { feedPlatforms, type FeedScope } from './feed-scope';
import FeedScopeFields from './FeedScopeFields.vue';
import PublisherSelect from './PublisherSelect.vue';

defineProps<{ disabled: boolean; targetPlatforms: ReadonlySet<string>; singleImport?: boolean }>();
const publishers = defineModel<string[]>('publishers', { required: true });
const platforms = defineModel<string[]>('platforms', { required: true });
const scope = defineModel<FeedScope>('scope', { required: true });
</script>

<template>
  <label class="field-label">发布者
    <PublisherSelect v-model="publishers" :disabled="disabled" />
  </label>
  <fieldset class="scope-field">
    <legend>发布者平台</legend>
    <n-checkbox-group v-model:value="platforms" :disabled="disabled" class="feed-platforms">
      <n-checkbox v-for="platform in feedPlatforms" :key="platform" :value="platform">{{ platformLabel(platform) }}</n-checkbox>
    </n-checkbox-group>
  </fieldset>
  <slot />
  <fieldset class="scope-field">
    <legend>抓取范围</legend>
    <div class="feed-platforms">
      <FeedScopeFields v-for="platform in feedPlatforms" :key="platform" v-model="scope" :platform="platform" :disabled="disabled || !targetPlatforms.has(platform)" :single-import="singleImport" />
    </div>
  </fieldset>
</template>
