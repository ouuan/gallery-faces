<script lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue';
import type { components } from './schema';

type Job = components['schemas']['Job'];
const activeKey = 'review-export.active';
const attemptedKey = 'review-export.attempted';
const started = shallowRef<Job>();
const submitting = ref(false);
</script>

<script setup lang="ts">
import { Download } from '@lucide/vue';
import { NButton } from 'naive-ui';
import { api, ApiError, send } from './api';
import { useLatestRequest } from './use-latest-request';

const props = defineProps<{ disabled: boolean; ids: number[]; state: string; filters: Record<string, string>; imageId?: number | null; total: number }>();
const root = '/admin/review-packages/exports';
const scope = computed(() => props.ids.length ? `所选 ${props.ids.length} 张` : props.state === 'image' && props.imageId ? `当前图片 #${props.imageId}` : `全部结果 ${props.total} 张`);
const restoring = ref(!!sessionStorage.getItem(activeKey));
const job = ref<Job | null>(null);
const error = ref('');
const read = useLatestRequest();
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
onScopeDispose(() => { disposed = true; clearTimeout(timer); });
onMounted(() => { if (restoring.value) void check(); });
watch(started, result => { if (result) { read.cancel(); update(result); } });
const download = computed(() => `/api/v1${root}/${job.value?.id}/download`);

function update(result: Job) {
  if (disposed) return;
  clearTimeout(timer);
  restoring.value = false;
  error.value = '';
  job.value = result;
  if (result.status === 'building' || result.status === 'ready') timer = setTimeout(check, 1000);
  else {
    sessionStorage.removeItem(activeKey);
    sessionStorage.removeItem(attemptedKey);
  }
  if (result.status === 'ready' && sessionStorage.getItem(attemptedKey) !== result.id) {
    sessionStorage.setItem(attemptedKey, result.id);
    const link = document.createElement('a');
    link.href = download.value;
    link.download = `review-${result.id}.zip`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.click();
  }
}
async function check() {
  const id = sessionStorage.getItem(activeKey);
  if (!id || disposed) return;
  clearTimeout(timer);
  const signal = read.start();
  try {
    const result = await api<Job>(`${root}/${encodeURIComponent(id)}`, { signal });
    if (!signal.aborted && sessionStorage.getItem(activeKey) === id) update(result);
  } catch (cause) {
    if (signal.aborted) return;
    error.value = (cause as Error).message;
    if (cause instanceof ApiError && cause.status === 404) {
      sessionStorage.removeItem(activeKey);
      sessionStorage.removeItem(attemptedKey);
      restoring.value = false;
      job.value = null;
    } else timer = setTimeout(check, 5000);
  }
}
async function start() {
  if (props.disabled || submitting.value || restoring.value || job.value?.status === 'building') return;
  error.value = '';
  submitting.value = true;
  try {
    const result: Job = await send(root, { ids: props.ids, state: props.state === 'image' ? 'all' : props.state,
      image_id: props.imageId ?? null, ...props.filters });
    sessionStorage.setItem(activeKey, result.id);
    started.value = result;
  } catch (cause) { error.value = (cause as Error).message; }
  finally { submitting.value = false; }
}
</script>

<template>
  <n-button :disabled="disabled || submitting || restoring || job?.status === 'building'" @click="start">
    <template #icon><Download /></template>{{ submitting ? '正在提交…' : restoring ? '正在查询导出任务…' : job?.status === 'building' ? `正在生成 ${job.done} / ${job.total}` : `导出${scope}` }}
  </n-button>
  <span v-if="job?.status === 'ready'" role="status" class="download-ready">审核包已就绪 ·
    <a :href="download" download target="_blank" rel="noopener" title="未开始或中断时可重试；未下载的文件保留一小时">手动下载</a>
  </span>
  <span v-if="error || job?.status === 'failed' || job?.status === 'expired'" role="alert" class="error-text">
    {{ error || job?.error || '审核包不可用，请重新导出' }}
    <n-button v-if="restoring || job?.status === 'building' || job?.status === 'ready'" @click="check">重试查询</n-button>
  </span>
</template>

<style scoped>
.download-ready { color: var(--muted); font-size: 13px; }
.download-ready a { display: inline-flex; min-height: 44px; align-items: center; }
</style>
