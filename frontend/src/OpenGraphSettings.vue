<script setup lang="ts">
import { NInput } from "naive-ui";
defineProps<{ label: string; suffix: string; disabled: boolean }>();
const settings = defineModel<Record<string, string>>({ required: true });
</script>

<template>
  <section :aria-label="label + '分享设置'">
  <h3>{{ label }}</h3>
  <label class="field-label">分享标题<n-input
    v-model:value="settings['og_title' + suffix]"
    :input-props="{ 'aria-label': label + '分享标题' }"
    :placeholder="settings.site_title" maxlength="100" show-count :disabled="disabled"
  /></label>
  <label class="field-label">分享描述<n-input
    v-model:value="settings['og_description' + suffix]" type="textarea"
    :input-props="{ 'aria-label': label + '分享描述' }"
    placeholder="简要介绍本站" maxlength="500" show-count
    :autosize="{ minRows: 2, maxRows: 5 }" :disabled="disabled"
  /></label>
  <label class="field-label">预览图 URL<n-input
    v-model:value="settings['og_image' + suffix]"
    :input-props="{ 'aria-label': label + '预览图 URL', type: 'url' }"
    placeholder="https://example.com/share.jpg" maxlength="2048" :disabled="disabled"
  /></label>
  <label class="field-label">站点 URL<n-input
    v-model:value="settings['og_url' + suffix]"
    :input-props="{ 'aria-label': label + '站点 URL', type: 'url' }"
    placeholder="https://example.com/" maxlength="2048" :disabled="disabled"
  /></label>
  </section>
</template>
