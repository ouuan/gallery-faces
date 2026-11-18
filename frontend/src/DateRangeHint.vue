<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { ref, watch, onUnmounted } from "vue";
import { ApiError, siteTimezone } from "./api";
import { dateRangeLabel, loadDateBounds } from "./date-range";

const props = defineProps<{ start: string; end: string }>();
const loading = ref(false);
const label = ref(""), error = ref(""), retryable = ref(false);
let version = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
function refresh() {
  const current = ++version;
  clearTimeout(timer);
  loading.value = true;
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
    } finally {
      if (current === version) loading.value = false;
    }
  }, 250);
}
watch(() => [props.start, props.end, siteTimezone.value], refresh, { immediate: true });
onUnmounted(() => { ++version; clearTimeout(timer); });
</script>

<template>
  <div class="hint loading-region date-range-hint" :aria-busy="loading">
  <LoadingOverlay :show="loading" label="正在加载时区信息" />
  <p role="status" :style="{ visibility: loading ? 'hidden' : undefined }">
    <template v-if="label && !error">
      <span v-for="(part, index) in label.split(/(UTC[+-]\d+(?::\d{2}){0,2})/)" :key="index" :class="{ 'utc-offset': part.startsWith('UTC') }">{{ part }}</span>
    </template>
    <template v-else>{{ error || "正在加载时区信息" }}</template>
    <button v-if="retryable" type="button" class="text-button" @click="refresh">重试</button>
  </p>
  </div>
</template>

<style scoped>
.date-range-hint { min-height: 2em; }
.utc-offset { white-space: nowrap; }
</style>
