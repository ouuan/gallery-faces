<script lang="ts">
import { reactive } from "vue";
const drafts = reactive<Record<number, string>>({});
const cooldownUntil = reactive({ value: 0 });
</script>
<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { useConfirm } from "./confirm";
import { computed, onUnmounted, ref, watch } from "vue";
import { NAlert, NButton, NInput, NTag, useMessage } from "naive-ui";
import { api, send, ApiError, dateLabel } from "./api";
import { useLatestRequest } from "./use-latest-request";
import type { components } from "./schema";
type Feedback = components["schemas"]["FeedbackOutput"];
type Page = components["schemas"]["FeedbackPage"];
const props = defineProps<{ imageId: number; admin?: boolean; pendingCount?: number }>();
const emit = defineEmits<{ changed: [] }>();
const message = useMessage();
const confirm = useConfirm();
const items = ref<Feedback[]>([]), cursor = ref<number | null>(null);
const loading = ref(false), busy = ref(false), error = ref(""), submitError = ref("");
const now = ref(Date.now());
const timer = window.setInterval(() => { now.value = Date.now(); }, 1000);
let version = 0, mounted = true;
const feedbackRequest = useLatestRequest();
onUnmounted(() => { mounted = false; version++; clearInterval(timer); });
const remaining = computed(() => Math.max(0, Math.ceil((cooldownUntil.value - now.value) / 1000)));
const draft = computed({ get: () => drafts[props.imageId] || "", set: (value: string) => { drafts[props.imageId] = value; } });
const endpoint = computed(() => props.admin ? `/admin/images/${props.imageId}/feedback` : null);
async function load(more = false) {
  const current = ++version;
  const signal = feedbackRequest.start();
  if (!endpoint.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const result = await api<Page>(endpoint.value + (more && cursor.value ? `?before_id=${cursor.value}` : ""), { signal });
    if (current !== version) return;
    items.value = more ? [...items.value, ...result.items] : result.items;
    cursor.value = result.next_cursor;
  } catch (e) {
    if (current === version) error.value = (e as Error).message;
  } finally {
    if (current === version) loading.value = false;
  }
}
async function submit() {
  if (busy.value || remaining.value || !draft.value.trim()) return;
  const imageId = props.imageId;
  const submittedDraft = draft.value;
  busy.value = true;
  submitError.value = "";
  try {
    await send(`/images/${imageId}/feedback`, { content: submittedDraft.trim() });
    if (drafts[imageId] === submittedDraft) drafts[imageId] = "";
    if (!mounted || imageId !== props.imageId) return;
    message.success("反馈已提交，仅管理员可见");
    emit("changed");
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) cooldownUntil.value = Date.now() + (e.retryAfter || 60) * 1000;
    if (mounted && imageId === props.imageId) submitError.value = (e as Error).message;
  } finally { if (mounted) busy.value = false; }
}
async function moderate(item: Feedback, remove = false) {
  if (busy.value || (remove && !await confirm("确定删除此反馈吗？删除后无法恢复。"))) return;
  busy.value = true;
  submitError.value = "";
  try {
    await send(`/admin/feedback/${item.id}`, remove ? {} : { status: item.status === "pending" ? "resolved" : "pending" }, remove ? "DELETE" : "PUT");
    if (!mounted) return;
    await load();
    emit("changed");
  } catch (e) { if (mounted) submitError.value = (e as Error).message; }
  finally { if (mounted) busy.value = false; }
}
watch(endpoint, () => { items.value = []; cursor.value = null; void load(); }, { immediate: true });
</script>
<template>
  <LoadingOverlay v-if="admin && !items.length && !error && !submitError" :show="loading" label="正在加载反馈…" />
  <section v-if="!admin || error || submitError || items.length" class="feedback-panel loading-region" :aria-busy="loading" aria-label="图片反馈">
    <h3>图片反馈<span v-if="!admin && pendingCount" class="muted">（已有 {{ pendingCount }} 条反馈）</span><span v-if="admin && pendingCount" class="muted">（{{ pendingCount }} 条待处理）</span></h3>
    <template v-if="admin">
      <n-alert v-if="error" type="error">{{ error }} <n-button :disabled="loading" @click="load()">重试</n-button></n-alert>
      <LoadingOverlay :show="loading" label="正在加载反馈…" />
      <ul class="feedback-list">
        <li v-for="item in items" :key="item.id">
          <div class="feedback-meta"><n-tag size="small" :type="item.status === 'pending' ? 'warning' : 'default'">{{ item.status === 'pending' ? '待处理' : '已处理' }}</n-tag><time :datetime="item.created_at">{{ dateLabel(item.created_at) }}</time></div>
          <p class="feedback-content">{{ item.content }}</p>
          <div class="feedback-actions">
            <n-button :disabled="busy || loading" @click="moderate(item)">{{ item.status === 'pending' ? '标记已处理' : '恢复待处理' }}</n-button>
            <n-button type="error" secondary :disabled="busy || loading" @click="moderate(item, true)">删除反馈</n-button>
          </div>
        </li>
      </ul>
      <n-button v-if="cursor" :disabled="loading || busy" @click="load(true)">加载更多反馈</n-button>
    </template>
    <n-alert v-if="submitError" type="error">{{ submitError }}</n-alert>
    <form v-if="!admin" class="feedback-form" @submit.prevent="submit">
      <n-input :input-props="{ id: `feedback-${imageId}`, 'aria-label': '反馈内容' }" v-model:value="draft" type="textarea" :maxlength="1000" show-count :autosize="{ minRows: 3, maxRows: 8 }" :disabled="busy" placeholder="例如：人物识别有误、来源需要补充" />
      <div class="loading-region"><p class="hint" :style="{ visibility: remaining ? 'hidden' : undefined }">反馈仅管理员可见</p>
      <LoadingOverlay :show="remaining > 0" error :label="`提交过于频繁，${remaining} 秒后可重试`" /></div>
      <n-button class="stable-loading-button" type="primary" attr-type="submit" :loading="busy" :disabled="busy || remaining > 0 || !draft.trim()">提交反馈</n-button>
    </form>
  </section>
</template>
<style scoped>
.feedback-panel { margin-top: 24px; min-width: 0; }
.feedback-list { list-style: none; padding: 0; margin: 12px 0; }
.feedback-list li { border-bottom: 1px solid var(--line); padding: 16px 0; }
.feedback-meta, .feedback-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.feedback-meta time { color: var(--muted); font-size: 13px; }
.feedback-content { white-space: pre-wrap; overflow-wrap: anywhere; margin: 12px 0; }
.feedback-form { margin-top: 12px; display: grid; gap: 8px; }
.feedback-form .hint { margin: 0; }
</style>
