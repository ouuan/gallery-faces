<script setup lang="ts">
import { computed, onScopeDispose, ref } from 'vue';
import { Download } from '@lucide/vue';
import { NButton } from 'naive-ui';
import { api, send } from './api';
import { useLatestRequest } from './use-latest-request';
import type { components } from './schema';

const props = defineProps<{ disabled: boolean; ids: number[]; state: string; filters: Record<string, string>; imageId?: number | null; total: number }>();
type Job = components['schemas']['Job'];
const root = '/admin/review-packages/exports';
const scope = computed(() => props.ids.length ? `所选 ${props.ids.length} 张` : props.state === 'image' && props.imageId ? `当前图片 #${props.imageId}` : `全部结果 ${props.total} 张`);
const submitting = ref(false);
const job = ref<Job | null>(null);
const error = ref('');
const read = useLatestRequest();
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
let attemptedId: string | undefined;
onScopeDispose(() => { disposed = true; clearTimeout(timer); });
const download = computed(() => `/api/v1${root}/${job.value?.id}/download`);

function update(result: Job) {
  if (disposed) return;
  job.value = result;
  if (result.status === 'building') timer = setTimeout(check, 1000);
  if (result.status === 'ready' && attemptedId !== result.id) {
    attemptedId = result.id;
    const link = document.createElement('a');
    link.href = download.value;
    link.download = `review-${result.id}.zip`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.click();
  }
}
async function check() {
  if (!job.value || disposed) return;
  error.value = '';
  const signal = read.start();
  try { update(await api<Job>(`${root}/${job.value.id}`, { signal })); }
  catch (cause) { if (!signal.aborted) error.value = (cause as Error).message; }
}
async function start() {
  if (props.disabled || submitting.value || job.value?.status === 'building') return;
  error.value = '';
  submitting.value = true;
  try {
    update(await send(root, { ids: props.ids, state: props.state === 'image' ? 'all' : props.state,
      image_id: props.imageId ?? null, ...props.filters }));
  } catch (cause) { error.value = (cause as Error).message; }
  finally { submitting.value = false; }
}
</script>

<template>
  <n-button :disabled="disabled || submitting || job?.status === 'building'" @click="start">
    <template #icon><Download /></template>{{ submitting ? '正在提交…' : job?.status === 'building' ? `正在生成 ${job.done} / ${job.total}` : `导出${scope}` }}
  </n-button>
  <span v-if="job?.status === 'ready'" role="status" class="download-ready">审核包已就绪 ·
    <a :href="download" download target="_blank" rel="noopener" title="未开始或中断时可重试；未下载的文件保留一小时">手动下载</a>
  </span>
  <span v-if="error || job?.status === 'failed' || job?.status === 'expired'" role="alert" class="error-text">
    {{ error || job?.error || '审核包不可用，请重新导出。' }}
    <n-button v-if="job?.status === 'building'" @click="check">重试查询</n-button>
  </span>
</template>

<style scoped>
.download-ready { color: var(--muted); font-size: 13px; }
.download-ready a { display: inline-flex; min-height: 44px; align-items: center; }
</style>
