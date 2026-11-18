<script setup lang="ts">
import { ref, watch, onUnmounted } from "vue";
import { ApiError, siteTimezone } from "./api";
import { dateRangeLabel, loadDateBounds } from "./date-range";

const props = defineProps<{ start: string; end: string }>();
const label = ref(""), error = ref(""), retryable = ref(false);
let version = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
function refresh() {
  const current = ++version;
  clearTimeout(timer);
  label.value = "";
  error.value = "";
  retryable.value = false;
  const { start, end } = props;
  const zone = siteTimezone.value;
  timer = setTimeout(async () => {
    try {
      const result = await loadDateBounds(start, end, zone);
      if (current === version) label.value = dateRangeLabel(result);
    } catch (e) {
      if (current !== version) return;
      const invalid = e instanceof ApiError && e.status === 400;
      error.value = invalid ? e.message : "时区信息加载失败";
      retryable.value = !invalid;
    }
  }, 250);
}
watch(() => [props.start, props.end, siteTimezone.value], refresh, { immediate: true });
onUnmounted(() => { ++version; clearTimeout(timer); });
</script>

<template>
  <p class="hint" role="status">
    <template v-if="label && !error">
      <span v-for="(part, index) in label.split(/(UTC[+-]\d+(?::\d{2}){0,2})/)" :key="index" :class="{ 'utc-offset': part.startsWith('UTC') }">{{ part }}</span>
    </template>
    <template v-else>{{ error || "正在加载时区信息" }}</template>
    <button v-if="retryable" type="button" class="text-button" @click="refresh">重试</button>
  </p>
</template>

<style scoped>
.utc-offset { white-space: nowrap; }
</style>
