<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { useReviewShortcuts } from "./review-shortcuts";
import { computed, ref, watch, onUnmounted } from "vue";
import { NButton, NModal, NSelect, NAlert, useMessage } from "naive-ui";
import { Copy } from "@lucide/vue";
import { api, send, platformLabel, dateLabel, type Source } from "./api";
import { useLibrary } from "./store";
import { useReviewImages } from "./use-review-images";
import { useLatestRequest } from "./use-latest-request";

type CandidateImage = {
  id: number; width: number; height: number; group_id: number;
  people: { name: string }[]; sources: Source[];
};
type Candidate = { a: number; b: number; decision: string; score: number | null; images: CandidateImage[] };
const store = useLibrary(), message = useMessage();
const rows = ref<Candidate[]>([]), statuses = ref<string[]>(["pending"]);
const statusOptions = [
  { value: "pending", label: "待审核" }, { value: "auto", label: "自动合并" },
  { value: "merge", label: "人工合并" }, { value: "separate", label: "不是重复／已拆分" },
];
const current = ref(0), saving = ref(false), loading = ref(false), error = ref("");
const details = ref<CandidateImage | null>(null);
const row = computed(() => rows.value[current.value]);
const blocked = computed(() => saving.value || loading.value || !!error.value);
const { urls: imageUrls, failed: failedImages } = useReviewImages(() => row.value?.images.map(image => image.id) ?? []);
const people = (image: CandidateImage) => image.people.map(p => p.name).join("、") || "未知人物";
function publishers(image: CandidateImage) {
  return [...new Map(image.sources.map(source => [
    `${source.platform}:${source.author?.toLowerCase() || store.publisherName(source)}`,
    `${platformLabel(source.platform)} · ${store.publisherName(source)}`,
  ])).values()];
}
let request = 0;
const listRequest = useLatestRequest();
let successors: Candidate[] | null = null;
async function load() {
  const signal = listRequest.start();
  const id = ++request;
  loading.value = true;
  error.value = "";
  const query = new URLSearchParams();
  statuses.value.forEach(value => query.append("decision", value));
  try {
    const result = await api<Candidate[]>(`/admin/duplicates?${query}`, { signal });
    if (id !== request) return;
    const next = successors?.map(pair => result.findIndex(r => r.a === pair.a && r.b === pair.b)).find(index => index >= 0);
    current.value = successors ? (next ?? Math.max(0, result.length - 1)) : 0;
    rows.value = result;
    successors = null;
  } catch (e) {
    if (id === request) error.value = `${successors ? "已保存，列表刷新失败：" : "加载失败："}${(e as Error).message}`;
  } finally {
    if (id === request) loading.value = false;
  }
}
watch(statuses, () => { successors = null; void load(); }, { immediate: true });
onUnmounted(() => { request++; });
function moveGroup(index: number) {
  if (blocked.value || index < 0 || index >= rows.value.length) return;
  current.value = index;
}
useReviewShortcuts({
  arrowleft: { run: () => moveGroup(current.value - 1), enabled: () => current.value > 0 },
  arrowright: { run: () => moveGroup(current.value + 1), enabled: () => current.value < rows.value.length - 1 },
  m: { run: () => decide("merge") },
  x: { run: () => decide("separate") },
}, () => !!row.value && !blocked.value && !details.value);
async function decide(action: "merge" | "separate") {
  if (blocked.value || !row.value) return;
  saving.value = true;
  const { a, b } = row.value;
  try {
    await send("/admin/duplicates", { a, b, action });
    successors = rows.value.slice(current.value + 1);
    await load();
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="duplicate-filter"><label for="duplicate-status">审核状态</label>
    <n-select id="duplicate-status" v-model:value="statuses" multiple clearable :disabled="saving" :options="statusOptions" placeholder="全部状态" :input-props="{ 'aria-label': '审核状态' }" />
  </div>
  <n-alert v-if="error" type="error">{{ error }} <n-button @click="load()">重试加载</n-button></n-alert>
  <div class="duplicate-content loading-region" :aria-busy="loading">
  <LoadingOverlay :show="loading" label="正在加载候选…" />
  <div v-if="!row && !error" :style="{ visibility: loading ? 'hidden' : undefined }" class="duplicates-empty">
    <Copy :size="40" /><h2>当前状态下暂无重复图片候选</h2>
    <p>导入图片后自动检测相同文件和尺寸、压缩变体</p>
  </div>
  <article v-if="row" class="duplicate-review" aria-label="重复图片审核">
    <nav class="duplicate-navigation" aria-label="候选组切换">
      <n-button :disabled="blocked || current === 0" @click="moveGroup(current - 1)" aria-label="上一组" aria-keyshortcuts="ArrowLeft">上一组<kbd class="shortcut-key" aria-hidden="true">←</kbd></n-button>
      <span aria-live="polite">第 {{ current + 1 }} / {{ rows.length }} 组</span>
      <n-button :disabled="blocked || current === rows.length - 1" @click="moveGroup(current + 1)" aria-label="下一组" aria-keyshortcuts="ArrowRight">下一组<kbd class="shortcut-key" aria-hidden="true">→</kbd></n-button>
    </nav>
    <div class="duplicate-heading">
      <h3>#{{ row.a }} 与 #{{ row.b }}</h3>
      <span>{{ statusOptions.find(option => option.value === row.decision)?.label || row.decision }} · SSIM {{ row.score?.toFixed(3) ?? '—' }}</span>
    </div>
    <div class="duplicate-pair">
      <section v-for="image in row.images" :key="image.id" class="duplicate-photo" :aria-label="`图片 #${image.id}`">
        <div class="duplicate-image loading-region" :aria-busy="!imageUrls.has(image.id) && !failedImages.has(image.id)">
          <LoadingOverlay :show="!imageUrls.has(image.id) || failedImages.has(image.id)" center :error="failedImages.has(image.id)" :label="failedImages.has(image.id) ? '图片加载失败' : '正在加载图片…'" />
          <img v-if="imageUrls.has(image.id) && !failedImages.has(image.id)" :src="imageUrls.get(image.id)" :alt="`重复图片候选 #${image.id}`" @error="failedImages.add(image.id)" />

        </div>
        <div class="duplicate-caption">
          <p>{{ image.width }} × {{ image.height }}</p>
          <p class="duplicate-people">{{ people(image) }}</p>
          <div class="duplicate-publishers"><p v-for="publisher in publishers(image)" :key="publisher">{{ publisher }}</p><p v-if="!image.sources.length">暂无来源</p></div>
          <n-button :aria-label="`查看图片 #${image.id} 详情`" @click="details = image">查看详情</n-button>
        </div>
      </section>
    </div>
    <div class="duplicate-actions">
      <n-button class="stable-loading-button" type="primary" :disabled="blocked" :loading="saving" aria-label="合并为一组" aria-keyshortcuts="m" @click="decide('merge')">合并为一组<kbd class="shortcut-key" aria-hidden="true">M</kbd></n-button>
      <n-button :disabled="blocked" :aria-label="row.images[0]?.group_id === row.images[1]?.group_id ? '拆分图片' : '不是重复'" aria-keyshortcuts="x" @click="decide('separate')">{{ row.images[0]?.group_id === row.images[1]?.group_id ? '拆分图片' : '不是重复' }}<kbd class="shortcut-key" aria-hidden="true">X</kbd></n-button>
    </div>
  </article>
  </div>
  <n-modal :show="!!details" @update:show="!$event && (details = null)" preset="card" role="dialog" aria-modal="true" :title="`图片 #${details?.id} 详情`" class="duplicate-details-dialog" :bordered="false">
    <template v-if="details">
      <p>{{ details.width }} × {{ details.height }}</p>
      <h3>人物</h3><p>{{ people(details) }}</p>
      <h3>来源</h3>
      <p v-if="!details.sources.length" class="muted">暂无来源</p>
      <p v-for="source in details.sources" :key="source.id">
        <a :href="source.url" target="_blank" rel="noopener noreferrer">{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }} · {{ dateLabel(source.published_at) }}</a>
      </p>
      <p class="hint">拆分后的图片不会再次自动合并</p>
    </template>
  </n-modal>
</template>

<style scoped>
.duplicate-content { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.duplicate-filter { display: flex; align-items: center; gap: 12px; flex-shrink: 0; margin-bottom: 12px; }
.duplicate-filter label { flex-shrink: 0; }
.duplicate-filter .n-select { max-width: 560px; }
.duplicate-publishers { max-height: 4.8em; overflow-y: auto; overflow-wrap: anywhere; }
.duplicate-review { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 12px; }
.duplicate-navigation, .duplicate-heading, .duplicate-actions { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.duplicate-navigation { justify-content: space-between; font-variant-numeric: tabular-nums; }
.duplicate-heading { justify-content: space-between; font-size: 13px; }
.duplicate-pair { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.duplicate-photo { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
.duplicate-image { flex: 1; min-height: 0; min-width: 0; display: flex; align-items: center; justify-content: center; background: var(--panel); }
.duplicate-image img { display: block; width: 100%; height: 100%; object-fit: scale-down; }
.duplicate-caption { flex-shrink: 0; min-width: 0; font-size: 13px; }
.duplicate-people { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.duplicate-caption .n-button { margin-top: 4px; }
.duplicates-empty { flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 8px; text-align: center; }
@media (max-width: 640px), (max-height: 600px) {
  .duplicate-review { gap: 8px; }
  .duplicate-pair { gap: 12px; }
}
@media (max-height: 600px) {
  .duplicate-filter { margin-bottom: 0; }
  .duplicate-publishers { max-height: 1.6em; }
  .duplicate-publishers p { display: inline; margin-right: 8px; }
  .duplicate-caption { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 8px; }
  .duplicate-caption .n-button { grid-column: 2; grid-row: 1 / 4; margin: 0; }
}
@media (min-width: 700px) and (max-height: 600px) {
  .duplicate-review { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: auto minmax(0, 1fr) auto; }
  .duplicate-heading { justify-content: flex-end; }
  .duplicate-pair, .duplicate-actions { grid-column: 1 / -1; }
  .duplicate-photo { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: stretch; }
  .duplicate-caption { display: flex; flex-direction: column; justify-content: center; gap: 0; }
}
</style>
<style>
@media (max-height: 600px) { .duplicates-shell .admin-content > h1 { display: none; } }
.duplicate-details-dialog { width: min(560px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); overflow-y: auto; overflow-wrap: anywhere; }
.duplicate-details-dialog h3 { margin: 16px 0 8px; }
.duplicate-details-dialog p + p { margin-top: 8px; }
</style>
