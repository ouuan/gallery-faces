<script lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
const importKey = 'review-import.active';
const importId = ref(sessionStorage.getItem(importKey));
const uploading = ref(false);
</script>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router';
import { ArrowRight, RefreshCw, SignalHigh, SignalLow, SignalMedium, Upload } from '@lucide/vue';
import { NAlert, NButton, NCheckbox, NModal, NRadio, NRadioGroup, NSelect } from 'naive-ui';
import { api, ApiError, send } from './api';
import ListPagination from './ListPagination.vue';
import ReviewPackageImage from './ReviewPackageImage.vue';
import { useLatestRequest } from './use-latest-request';
import type { components } from './schema';

const kinds = {
  match: '匹配人物', remove_face: '删除误检人脸', add_face: '补画人脸框', create_person: '新建人物', add_reference: '添加参考图', recycle: '整组移入回收站',
  set_person_name_ja: '补充人物日语名', set_group_name_ja: '补充分组日语名', add_person_account: '关联人物账号',
  add_person_group: '将人物加入分组', correct_source: '更正帖子来源', review_outcome: '记录逐图审核结论',
} satisfies Record<components['schemas']['QueueItem']['proposal']['kind'], string>;
type Schema = components['schemas'];
type Suggestion = Schema['QueueItem'];
type Result = Schema['QueuePage'];
type Decision = Schema['Decision']['decision'];
const root = '/admin/review-packages';
const confidenceTiers = { high: { label: '高', icon: SignalHigh }, medium: { label: '中', icon: SignalMedium }, low: { label: '低', icon: SignalLow } };
const route = useRoute();
const router = useRouter();
const statuses = [{ value: 'review', label: '建议与结论' }, { value: 'accepted', label: '已接受' }, { value: 'rejected', label: '已拒绝' }, { value: 'acknowledged', label: '已确认结论' }];
const status = computed(() => statuses.find(option => option.value === route.query.suggestion_status) ?? statuses[0]);
const page = computed(() => {
  const value = Number(route.query.suggestion_page);
  return Number.isSafeInteger(value) && value > 0 ? value : 1;
});
const result = ref<Result>({ items: [], total: 0, page: 1, page_size: 20 });
const pageCount = computed(() => Math.max(1, Math.ceil(result.value.total / result.value.page_size)));
const groups = computed(() => {
  const grouped = new Map<number, Suggestion[]>();
  for (const item of result.value.items) {
    if (!grouped.has(item.image_id)) grouped.set(item.image_id, []);
    grouped.get(item.image_id)!.push(item);
  }
  return [...grouped.values()];
});
const loading = ref(false);
const writing = ref(false);
const busy = computed(() => loading.value || writing.value);
const importNotice = ref('');
const importError = ref('');
const loadError = ref('');
const actionError = ref('');
const notice = ref('');
const failures = ref<Schema['Failure'][]>([]);
const selected = ref<number[]>([]);
const faceChoices = ref<Record<number, number>>({});
const fileInput = ref<HTMLInputElement>();
const confirmation = ref<Suggestion[]>([]);
const selectedItems = computed(() => result.value.items.filter(item => actionable(item) && selected.value.includes(item.id)));
const read = useLatestRequest();
let disposed = false;
onScopeDispose(() => { disposed = true; });

function navigate(value: string, number: number) {
  return router.replace({ query: { ...route.query, suggestion_status: value === 'review' ? undefined : value,
    suggestion_page: number === 1 ? undefined : String(number) } });
}
async function load() {
  if (disposed) return;
  const signal = read.start();
  loading.value = true;
  loadError.value = '';
  try {
    const data = await api<Result>(`${root}/suggestions?status=${status.value.value}&page=${page.value}&page_size=20`, { signal });
    if (signal.aborted) return;
    const actual = Math.max(1, Math.min(data.page, Math.ceil(data.total / data.page_size)));
    if (actual !== page.value) { await navigate(status.value.value, actual); return; }
    result.value = data;
    selected.value = selected.value.filter(id => data.items.some(item => item.id === id));
    for (const item of data.items) {
      if (!item.attachment || faceChoices.value[item.id] !== undefined) continue;
      const suggested = item.attachment.suggested_index;
      if (suggested !== null) faceChoices.value[item.id] = suggested;
    }
  } catch (cause) { if (!signal.aborted) loadError.value = (cause as Error).message; }
  finally { if (!signal.aborted) loading.value = false; }
}
watch([status, page], () => {
  selected.value = []; faceChoices.value = {}; failures.value = []; confirmation.value = []; actionError.value = '';
  result.value = { items: [], total: 0, page: page.value, page_size: 20 };
  void load();
}, { immediate: true });

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file || uploading.value || importId.value) return;
  uploading.value = true; importError.value = ''; importNotice.value = ''; notice.value = '';
  const body = new FormData();
  body.append('file', file);
  try {
    const job = await api<Schema['ImportJob']>(`${root}/imports`, { method: 'POST', body });
    sessionStorage.setItem(importKey, job.id);
    importId.value = job.id;
  } catch (cause) { importError.value = (cause as Error).message; }
  finally { uploading.value = false; }
}
watch(importId, (id, _, onCleanup) => {
  if (!id) return;
  const path = `${root}/imports/${encodeURIComponent(id)}`;
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  onCleanup(() => { controller.abort(); clearTimeout(timer); });
  async function poll() {
    try {
      const job = await api<Schema['ImportJob']>(path, { signal: controller.signal });
      if (controller.signal.aborted) return;
      importError.value = '';
      if (job.status === 'queued' || job.status === 'running') {
        timer = setTimeout(poll, 1000);
        return;
      }
      if (job.status === 'failed') importError.value = job.error || '导入失败，请重新上传。';
      else {
        importNotice.value = `已导入 ${job.added} 条建议，记录 ${job.recorded} 条审核结论，跳过 ${job.duplicates} 条重复记录。`;
        void load();
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      importError.value = (cause as Error).message;
      if (!(cause instanceof ApiError && cause.status === 404)) { timer = setTimeout(poll, 5000); return; }
    }
    sessionStorage.removeItem(importKey);
    importId.value = null;
  }
  void poll();
}, { immediate: true });
function reviewLink(image: number) { return { path: '/admin/review', query: { state: 'image', image } }; }
function actionable(item: Suggestion) { return item.status === 'pending' && item.proposal.kind !== 'review_outcome'; }
function itemLabel(item: Suggestion) { return item.proposal.kind === 'review_outcome' ? '结论' : '建议'; }
function toggle(id: number, checked: boolean) {
  selected.value = checked ? [...new Set([...selected.value, id])] : selected.value.filter(selectedId => selectedId !== id);
}
function canAccept(item: Suggestion) {
  if (item.proposal.kind === 'recycle' && (!item.scope_token || !item.member_ids.length)) return false;
  return !item.attachment || !!item.attachment.boxes[faceChoices.value[item.id]];
}
function destructive(item: Suggestion) { return ['recycle', 'remove_face'].includes(item.proposal.kind); }
function decide(decision: 'accept' | 'reject', items: Suggestion[]) {
  if (busy.value || !items.length || !items.every(actionable)) return;
  if (decision === 'accept' && items.some(item => !canAccept(item))) return;
  if (decision === 'accept' && items.some(destructive)) confirmation.value = [...items];
  else void apply(decision, items);
}
async function apply(decision: Decision, items: Suggestion[]) {
  if (writing.value || !items.length) return;
  confirmation.value = [];
  writing.value = true; notice.value = ''; actionError.value = ''; failures.value = [];
  try {
    const response: Schema['Decisions'] = await send(`${root}/decisions`, { decision,
      items: items.map(item => ({ id: item.id,
        ...(decision === 'accept' && item.attachment ? { face_index: faceChoices.value[item.id] } : {}),
        ...(decision === 'accept' && item.proposal.kind === 'recycle' ? { scope_token: item.scope_token } : {}) })) } satisfies Schema['Decision']);
    if (disposed) return;
    if (decision === 'acknowledge') {
      if (response.failures.length) actionError.value = response.failures[0].detail;
      else notice.value = '已确认审核结论。';
    } else {
      failures.value = response.failures;
      notice.value = `已${decision === 'accept' ? '接受' : '拒绝'} ${response.applied.length} 条建议。`;
    }
    selected.value = selected.value.filter(id => !response.applied.includes(id));
    await load();
  } catch (cause) { actionError.value = (cause as Error).message; }
  finally { writing.value = false; }
}
function positions(items: Suggestion[]) {
  return items.flatMap((item, index) => item.box ? [{ box: item.box, label: String(index + 1), active: selected.value.includes(item.id) }] : []);
}
function coords(box: number[]) { return `[${box.join(', ')}]`; }
function sourceFace(item: Suggestion) {
  const proposal = item.proposal;
  return item.face_token && proposal.kind === 'add_reference' && 'face_id' in proposal.source ? proposal.source.face_id : null;
}
function externalSource(item: Suggestion) {
  const proposal = item.proposal;
  return proposal.kind === 'add_reference' && 'attachment' in proposal.source ? proposal.source : null;
}
</script>

<template>
  <section class="queue" aria-label="建议复核">
    <header class="queue-tools">
      <div class="controls">
        <n-select aria-label="建议状态" :options="statuses" :value="status.value" :disabled="busy" @update:value="navigate($event, 1)" />
        <span v-if="!loading && !loadError" class="muted">共 {{ result.total }} 条记录</span>
      </div>
      <div class="controls">
        <n-button :disabled="busy" aria-label="刷新建议" title="刷新建议" @click="load"><template #icon><RefreshCw /></template></n-button>
        <input ref="fileInput" hidden type="file" accept=".json,.zip" @change="importFile" />
        <n-button :disabled="uploading || !!importId" :loading="uploading" @click="fileInput?.click()"><template #icon><Upload /></template>导入审核结果</n-button>
      </div>
    </header>
    <p v-if="importId || importNotice" role="status">{{ importId ? '正在后台导入审核结果，可以继续审核或离开此页。' : importNotice }}</p>
    <n-alert v-if="importError" type="error">{{ importError }}</n-alert>
    <p v-if="notice" role="status">{{ notice }}</p>
    <n-alert v-if="actionError" type="error">{{ actionError }}</n-alert>
    <n-alert v-if="failures.length" type="warning" title="以下建议未应用">
      <p v-for="failure in failures" :key="failure.id">建议 #{{ failure.id }}：{{ failure.detail }}</p>
    </n-alert>
    <n-alert v-if="loadError" type="error">{{ loadError }} <n-button @click="load">重试加载</n-button></n-alert>
    <template v-else>
      <div v-if="selectedItems.length" class="controls selection-tools" aria-label="批量决定">
        <strong>已选 {{ selectedItems.length }} 条</strong>
        <n-button type="primary" :disabled="busy || !selectedItems.every(canAccept)" @click="decide('accept', selectedItems)">接受所选</n-button>
        <n-button :disabled="busy" @click="decide('reject', selectedItems)">拒绝所选</n-button>
        <n-button quaternary :disabled="busy" @click="selected = []">取消选择</n-button>
      </div>
      <div v-if="!groups.length" class="empty-state" role="status">
        <h2>{{ loading ? '正在加载…' : status.value === 'review' ? '暂无建议或审核结论' : status.value === 'acknowledged' ? '暂无已确认结论' : `没有${status.label}的建议` }}</h2>
        <p v-if="!loading && status.value === 'review'">可导入 review-result.json 或含附件的结果 ZIP。</p>
      </div>
      <section v-for="items in groups" :key="items[0].image_id" class="image-group" :aria-label="`图片 #${items[0].image_id} 的审核记录`">
        <div class="image-column">
          <h3><router-link :to="reviewLink(items[0].image_id)">图片 #{{ items[0].image_id }}</router-link> <small>{{ items.length }} 条记录</small></h3>
          <ReviewPackageImage :src="`/api/v1/admin/media/${items[0].image_id}`" :fallback="`/api/v1/admin/media/${items[0].image_id}?thumbnail=true`"
            :width="items[0].width" :height="items[0].height" :alt="`图片 #${items[0].image_id}`" :boxes="positions(items)" />
          <p class="hint">{{ items[0].width }} × {{ items[0].height }} px</p>
        </div>
        <div class="suggestions">
          <article v-for="(item, index) in items" :key="item.id" :aria-label="`${itemLabel(item)} #${item.id}`">
            <header class="item-heading">
              <div class="proposal-title"><h4>{{ index + 1 }}. {{ kinds[item.proposal.kind] }}</h4>
                <span v-if="item.proposal.confidence" class="confidence" :class="item.proposal.confidence" title="Agent 对这条建议的判断，不是人脸匹配分数">
                  <component :is="confidenceTiers[item.proposal.confidence].icon" :size="16" aria-hidden="true" />Agent 置信度：{{ confidenceTiers[item.proposal.confidence].label }}
                </span>
              </div>
              <n-checkbox v-if="actionable(item)" :disabled="busy"
                :checked="selected.includes(item.id)" @update:checked="toggle(item.id, $event)">选择<span class="sr-only">建议 #{{ item.id }}</span></n-checkbox>
            </header>
            <p v-if="item.proposal.kind === 'review_outcome'">{{ item.proposed }}</p>
            <dl v-else class="change"><div><dt>当前</dt><dd>{{ item.current }}</dd></div><ArrowRight aria-hidden="true" /><div><dt>建议</dt><dd>{{ item.proposed }}</dd></div></dl>
            <p class="reason">{{ item.proposal.reason }}</p>
            <p v-if="item.box" class="hint">定位（x, y, 宽, 高）：{{ coords(item.box) }} px</p>
            <p v-if="item.proposal.kind === 'recycle'" class="hint">整组 {{ item.member_ids.length }} 张：<template v-for="(id, index) in item.member_ids" :key="id">{{ index ? '、' : '' }}<router-link :to="reviewLink(id)">#{{ id }}</router-link></template></p>
            <div v-if="sourceFace(item) || item.reference_ids.length" class="references">
              <figure v-if="sourceFace(item)"><img :src="`/api/v1/admin/faces/${sourceFace(item)}/crop?token=${item.face_token}`" alt="拟添加的图库人脸" loading="lazy" /><figcaption>来源人脸 #{{ sourceFace(item) }}</figcaption></figure>
              <figure v-for="id in item.reference_ids" :key="id"><img :src="`/api/v1/admin/references/${id}/crop`" :alt="`参考图 #${id}`" loading="lazy" /><figcaption>参考 #{{ id }}</figcaption></figure>
            </div>
            <div v-if="item.attachment" class="attachment">
              <strong>外部参考图</strong>
              <ReviewPackageImage :src="`/api/v1${root}/suggestions/${item.id}/attachment`" :alt="`建议 #${item.id} 的外部参考图`" :width="item.attachment.width" :height="item.attachment.height"
                :boxes="item.attachment.boxes.map((box, position) => ({ box, label: String(position + 1), active: position === faceChoices[item.id] }))" />
              <a v-if="externalSource(item)?.source_url" :href="externalSource(item)?.source_url ?? undefined" target="_blank" rel="noopener noreferrer">查看参考图来源</a>
              <template v-if="actionable(item)">
                <p v-if="!item.attachment.boxes.length" class="error-text">未检测到有效人脸，无法接受此建议。</p>
                <template v-else>
                  <p class="hint">{{ canAccept(item) ? `目标人脸 ${faceChoices[item.id] + 1}：${coords(item.attachment.boxes[faceChoices[item.id]])} px` : '请选择要加入参考库的人脸。' }}</p>
                  <n-radio-group v-model:value="faceChoices[item.id]" :name="`faces-${item.id}`" :disabled="busy" aria-label="参考图目标人脸" class="controls face-options">
                    <n-radio v-for="(_, position) in item.attachment.boxes" :key="position" :value="position">人脸 {{ position + 1 }}</n-radio>
                  </n-radio-group>
                </template>
              </template>
            </div>
            <footer class="item-footer">
              <span class="hint">{{ itemLabel(item) }} #{{ item.id }}</span>
              <div v-if="actionable(item)" class="controls">
                <n-button :disabled="busy" @click="decide('reject', [item])">拒绝</n-button>
                <n-button secondary type="primary" :disabled="busy || !canAccept(item)" @click="decide('accept', [item])">接受</n-button>
              </div>
              <n-button v-else-if="item.status === 'recorded' && item.proposal.kind === 'review_outcome'" :disabled="busy" @click="apply('acknowledge', [item])">确认</n-button>
            </footer>
          </article>
        </div>
      </section>
      <nav v-if="pageCount > 1" class="controls pagination" aria-label="建议分页"><ListPagination :page="page" :page-count="pageCount" :disabled="busy" @change="navigate(status.value, $event)" /></nav>
    </template>
    <n-modal :show="!!confirmation.length" @update:show="!$event && (confirmation = [])">
      <section class="form-dialog confirm-scope" role="dialog" aria-modal="true" aria-labelledby="confirm-scope-heading">
        <h2 id="confirm-scope-heading">确认接受 {{ confirmation.length }} 条建议？</h2>
        <p v-for="item in confirmation" :key="item.id"><strong>建议 #{{ item.id }} · {{ kinds[item.proposal.kind] }}</strong><br />
          <router-link :to="reviewLink(item.image_id)">图片 #{{ item.image_id }}</router-link><template v-if="item.proposal.kind === 'recycle'"> 的整组 {{ item.member_ids.length }} 张：<template v-for="(id, index) in item.member_ids" :key="id">{{ index ? '、' : '' }}<router-link :to="reviewLink(id)">#{{ id }}</router-link></template>。原图和大图将清理。</template>
          <template v-else-if="'face_id' in item.proposal"> · 人脸 #{{ item.proposal.face_id }}</template>
        </p>
        <div class="form-actions"><n-button @click="confirmation = []">取消</n-button><n-button type="error" @click="apply('accept', confirmation)">确认接受</n-button></div>
      </section>
    </n-modal>
  </section>
</template>

<style scoped>
.queue { display: grid; gap: 20px; container-type: inline-size; overflow-wrap: anywhere; }
.queue-tools, .item-heading, .item-footer, .controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; }
.queue-tools, .item-heading, .item-footer { justify-content: space-between; }
.queue-tools .n-select { width: 124px; }
.queue-tools .muted, .image-group small { font-size: 13px; color: var(--muted); font-weight: 400; }
.selection-tools { padding: 12px 16px; border-radius: 6px; background: var(--selection); }
.image-group { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 16px 24px; border-top: 1px solid var(--line); padding-top: 20px; }
.image-column { display: grid; gap: 8px; }
.image-column h3 { display: flex; align-items: baseline; gap: 12px; }
.suggestions { min-width: 0; }
article { display: grid; gap: 12px; }
article + article { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--line); }
.item-heading h4 { font-size: 16px; margin: 0; }
.proposal-title { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; }
.confidence { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted); }
.confidence.high { color: var(--accent); font-weight: 600; }
.confidence.medium { color: var(--text); }
.item-heading .n-checkbox, .face-options .n-radio { min-height: 44px; align-items: center; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.change { display: grid; grid-template-columns: minmax(0, 1fr) 16px minmax(0, 1fr); align-items: start; gap: 12px; margin: 0; padding: 12px 16px; border-radius: 4px; background: var(--panel); }
.change dt, figcaption { color: var(--muted); font-size: 13px; }
.change dd { margin: 4px 0 0; }
.change div:last-child dd { font-weight: 600; }
.change svg { align-self: center; width: 16px; color: var(--muted); }
.reason { white-space: pre-wrap; max-width: 72ch; }
.queue p { margin: 0; }
.references { display: flex; flex-wrap: wrap; gap: 12px; }
.references figure { margin: 0; }
.references img { display: block; width: 64px; height: 64px; object-fit: contain; background: var(--panel); border-radius: 4px; }
.attachment { display: grid; gap: 8px; }
.pagination { justify-content: center; }
.confirm-scope p { overflow-wrap: anywhere; margin: 12px 0; }
@container (min-width: 720px) {
  .image-group { grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); }
  .image-column { position: sticky; top: 88px; }
}
@container (max-width: 400px) { .queue-tools > :last-child { margin-inline-start: auto; } }
</style>
