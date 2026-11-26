<script lang="ts">
import { reactive } from "vue";
type Draft = { content: string; faceId: number | null; personId: number | null; notFace: boolean };
const drafts = reactive<Record<string, Draft>>({});
const cooldownUntil = reactive({ value: 0 });
</script>
<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { useConfirm } from "./confirm";
import { computed, onUnmounted, ref, watch } from "vue";
import { NAlert, NButton, NCheckbox, NInput, NTag, useMessage } from "naive-ui";
import { api, send, ApiError, dateLabel, facePosition, type Photo } from "./api";
import PersonSelect from './PersonSelect.vue';
import { useLatestRequest } from "./use-latest-request";
import type { components } from "./schema";
type Page = components["schemas"]["FeedbackPage"];
type Feedback = Page['items'][number];
const props = defineProps<{ imageId: number; admin?: boolean; group?: boolean; pendingCount?: number; photo?: Photo;
  defaultFace?: number; defaultPerson?: number | null; draftKey?: string; submitted?: (faceId: number | null) => void }>();
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
const key = computed(() => props.draftKey ?? `photo:${props.imageId}`);
const draft = computed(() => {
  drafts[key.value] ??= { content: '', faceId: props.defaultFace ?? null, personId: props.defaultPerson ?? null, notFace: false };
  return drafts[key.value]!;
});
const picking = ref(false);
const selectedIndex = computed(() => props.photo?.faces?.findIndex(face => face.id === draft.value.faceId) ?? -1);
const selected = computed(() => props.photo?.faces?.[selectedIndex.value]);
function selectFace(faceId: number | null) {
  if (draft.value.faceId !== faceId) { draft.value.personId = null; draft.value.notFace = false; }
  draft.value.faceId = faceId;
  picking.value = false;
}
function setNotFace(value: boolean) {
  draft.value.notFace = value;
  if (value) draft.value.personId = null;
}
const endpoint = computed(() => props.admin ? `/admin/images/${props.imageId}/feedback` : null);
async function load(more = false) {
  const current = ++version;
  const signal = feedbackRequest.start();
  if (!endpoint.value) { loading.value = false; return; }
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams();
    if (props.group) params.set("scope", "group");
    if (more && cursor.value) params.set("before_id", String(cursor.value));
    const result = await api<Page>(endpoint.value + (params.size ? `?${params}` : ""), { signal });
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
  if (busy.value || remaining.value || (!draft.value.content.trim() && !selected.value)) return;
  const imageId = props.imageId;
  const submittedKey = key.value, values = { ...draft.value }, face = selected.value, notify = props.submitted;
  busy.value = true;
  submitError.value = "";
  try {
    await send(`/images/${imageId}/feedback`, { content: values.content.trim(), ...(face && {
      face_id: face.id, face_revision: face.revision, suggested_person_id: values.personId, not_face: values.notFace }) });
    const saved = drafts[submittedKey];
    if (saved && saved.content === values.content && saved.faceId === values.faceId && saved.personId === values.personId && saved.notFace === values.notFace)
      Object.assign(saved, { content: '', faceId: null, personId: null, notFace: false });
    notify?.(face?.id ?? null);
    if (!mounted || imageId !== props.imageId) return;
    message.success("反馈已提交，仅管理员可见");
    emit("changed");
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) cooldownUntil.value = Date.now() + (e.retryAfter || 60) * 1000;
    if (mounted && imageId === props.imageId) submitError.value = (e as Error).message;
  } finally { if (mounted) busy.value = false; }
}
async function applySuggestion(item: Feedback) {
  if (busy.value) return;
  busy.value = true;
  submitError.value = '';
  try {
    await send(`/admin/feedback/${item.id}/apply`, {});
    if (mounted) { await load(); emit('changed'); }
  } catch (cause) { if (mounted) submitError.value = (cause as Error).message; }
  finally { if (mounted) busy.value = false; }
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
watch([endpoint, () => props.group], () => { items.value = []; cursor.value = null; void load(); }, { immediate: true });
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
          <div class="feedback-meta"><n-tag size="small" :type="item.status === 'pending' ? 'warning' : 'default'">{{ item.status === 'pending' ? '待处理' : '已处理' }}</n-tag><span v-if="group">图片 #{{ item.image_id }}</span><time :datetime="item.created_at">{{ dateLabel(item.created_at) }}</time></div>
          <p v-if="item.face_revision != null" class="feedback-content">{{ item.face_number ? `人脸 #${item.face_number}` : '已删除的人脸' }} · 提交时：{{ item.original_name || '未知人物' }}<br />{{ item.not_face ? '建议：不是人脸' : item.suggested_name ? `建议改为：${item.suggested_name}` : '对当前识别有疑问，未指定人物' }}</p>
          <p v-if="item.content" class="feedback-content">{{ item.content }}</p>
          <div class="feedback-actions">
            <n-button v-if="item.status === 'pending' && item.face_id && (item.suggested_person_id || item.not_face)" type="primary" :disabled="busy || loading" @click="applySuggestion(item)">应用并处理</n-button>
            <n-button :disabled="busy || loading" @click="moderate(item)">{{ item.status === 'pending' ? '标记已处理' : '恢复待处理' }}</n-button>
            <n-button type="error" secondary :disabled="busy || loading" @click="moderate(item, true)">删除反馈</n-button>
          </div>
        </li>
      </ul>
      <n-button v-if="cursor" :disabled="loading || busy" @click="load(true)">加载更多反馈</n-button>
    </template>
    <n-alert v-if="submitError" type="error">{{ submitError }}</n-alert>
    <form v-if="!admin" class="feedback-form" @submit.prevent="submit">
      <template v-if="photo?.faces?.length">
        <div class="feedback-actions"><n-button :disabled="busy" :aria-expanded="picking" @click="picking = !picking">
          <svg v-if="selected" class="selected-face-preview" width="36" height="36" :viewBox="selected.box.join(' ')" aria-hidden="true" focusable="false">
            <image :href="photo.image_url" :width="photo.width" :height="photo.height" />
          </svg>
          {{ selected ? `更换人脸 #${selectedIndex + 1}` : '选择人脸' }}
        </n-button>
          <n-button v-if="selected" :disabled="busy" @click="selectFace(null)">清除人脸</n-button></div>
        <div v-if="picking" class="feedback-picker" :style="{ aspectRatio: `${photo.width} / ${photo.height}` }">
          <img :src="photo.image_url" alt="选择要反馈的人脸" />
          <button v-for="(face, index) in photo.faces" :key="face.id" type="button" class="pick-box" :style="facePosition(face.box, photo.width, photo.height)"
            :aria-label="`选择人脸 #${index + 1}`" :aria-pressed="face.id === selected?.id" @click="selectFace(face.id)"><span>#{{ index + 1 }}</span></button>
        </div>
        <template v-if="selected">
          <PersonSelect v-if="!draft.notFace" v-model="draft.personId" :disabled="busy" accessible-label="建议人物" placeholder="建议人物（可不选）" />
          <n-checkbox :checked="draft.notFace" :disabled="busy" @update:checked="setNotFace">不是人脸</n-checkbox>
          <n-alert v-if="selected.locked" type="warning">这张人脸已经人工确认，你仍可提交反馈。</n-alert>
        </template>
      </template>
      <n-input :input-props="{ id: `feedback-${imageId}`, 'aria-label': '反馈内容' }" v-model:value="draft.content" type="textarea" :maxlength="1000" show-count :autosize="{ minRows: 3, maxRows: 8 }" :disabled="busy" :placeholder="selected ? '补充说明（可不填）' : '例如：人物识别有误、来源需要补充'" />
      <div class="loading-region"><p class="hint" :style="{ visibility: remaining ? 'hidden' : undefined }">反馈仅管理员可见</p>
      <LoadingOverlay :show="remaining > 0" error :label="`提交过于频繁，${remaining} 秒后可重试`" /></div>
      <n-button class="stable-loading-button" type="primary" attr-type="submit" :loading="busy" :disabled="busy || remaining > 0 || (!selected && !draft.content.trim())">提交反馈</n-button>
    </form>
  </section>
</template>
<style scoped>
.feedback-panel { margin-top: 24px; min-width: 0; }
.selected-face-preview { flex: none; margin-inline-end: 8px; border-radius: 4px; background: var(--bg); overflow: hidden; }
.feedback-picker { position: relative; }
.feedback-picker img { width: 100%; height: 100%; display: block; }
.pick-box { position: absolute; cursor: pointer; padding: 0; border: 2px solid white; outline: 1px solid #111; background: transparent; }
.pick-box span { position: absolute; left: 0; top: 0; font-size: 12px; background: #222; color: white; }
.pick-box:focus-visible { outline: 3px solid var(--accent); }
.feedback-list { list-style: none; padding: 0; margin: 12px 0; }
.feedback-list li { border-bottom: 1px solid var(--line); padding: 16px 0; }
.feedback-meta, .feedback-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.feedback-meta time { color: var(--muted); font-size: 13px; }
.feedback-content { white-space: pre-wrap; overflow-wrap: anywhere; margin: 12px 0; }
.feedback-form { margin-top: 12px; display: grid; gap: 8px; }
.feedback-form .hint { margin: 0; }
</style>
