<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { NAlert, NButton, NCheckbox, NSelect, useMessage } from "naive-ui";
import { api, send, dateLabel, platformLabel, type Source } from "./api";
import { useLibrary } from "./store";
import { useLatestRequest } from "./use-latest-request";
import { useReviewShortcuts } from "./review-shortcuts";
import LoadingOverlay from "./LoadingOverlay.vue";

type RestoreTask = { id: number; status: string; stage: string; error: string | null };
type TrashImage = {
  id: number; group_id: number; width: number; height: number; trashed_at: string;
  cleanup_pending: boolean; restore_task: RestoreTask | null; sources: Source[];
  faces: { id: number; person_id: number | null; locked: number; ignored: number }[];
};
const store = useLibrary(), message = useMessage(), request = useLatestRequest();
const images = ref<TrashImage[]>([]), selected = ref<number[]>([]);
const page = ref(1), total = ref(0), current = ref(0);
const loading = ref(false), busy = ref(false), error = ref("");
const directories = ref<string[]>([]), directory = ref<string | null>(null), directoryError = ref("");
const failedImages = ref(new Set<number>());
const active = computed(() => images.value[current.value]);
const targets = computed(() => selected.value.length ? selected.value : active.value ? [active.value.id] : []);
const pages = computed(() => Math.max(1, Math.ceil(total.value / 50)));
const restoring = (image: TrashImage) => !!image.restore_task && ["queued", "running"].includes(image.restore_task.status);
const canRestore = computed(() => images.value.some(image => targets.value.includes(image.id) && !restoring(image)));
let timer: ReturnType<typeof setTimeout> | undefined;
let stopped = false;

function schedulePoll() {
  clearTimeout(timer);
  if (!stopped && images.value.some(image => restoring(image) || image.cleanup_pending)) {
    timer = setTimeout(() => {
      if (busy.value || loading.value || document.hidden) schedulePoll();
      else void load(true);
    }, 2500);
  }
}
async function load(quiet = false) {
  const signal = request.start();
  if (!quiet) loading.value = true;
  error.value = "";
  const activeId = active.value?.id;
  try {
    const result = await api<{ items: TrashImage[]; total: number; page: number }>(`/admin/trash?page=${page.value}`, { signal });
    if (signal.aborted) return;
    const hadRestoring = images.value.some(restoring);
    images.value = result.items;
    page.value = result.page;
    total.value = result.total;
    selected.value = selected.value.filter(id => images.value.some(image => image.id === id));
    const index = images.value.findIndex(image => image.id === activeId);
    current.value = index >= 0 ? index : Math.min(current.value, Math.max(0, images.value.length - 1));
    if (hadRestoring) await store.load();
  } catch (e) {
    if (!signal.aborted) error.value = (e as Error).message;
  } finally {
    if (!signal.aborted) { loading.value = false; schedulePoll(); }
  }
}
function move(index: number) {
  if (!busy.value && !loading.value && index >= 0 && index < images.value.length) current.value = index;
}
async function changePage(value: number) {
  page.value = value;
  current.value = 0;
  selected.value = [];
  await load();
}
async function restore() {
  if (busy.value || !canRestore.value) return;
  busy.value = true;
  try {
    const ids = images.value.filter(image => targets.value.includes(image.id) && !restoring(image)).map(image => image.id);
    await send("/admin/images/actions", { action: "restore", ids, directory: directory.value });
    message.success(`已安排恢复 ${ids.length} 张图片，完成后返回图库`);
    await load(true);
  } catch (e) { message.error((e as Error).message); }
  finally { busy.value = false; schedulePoll(); }
}
async function cancel() {
  const task = active.value?.restore_task;
  if (!task || busy.value) return;
  busy.value = true;
  try {
    await send(`/admin/tasks/${task.id}/cancel`, {});
    message.success("已请求取消恢复");
    await load(true);
  } catch (e) { message.error((e as Error).message); }
  finally { busy.value = false; schedulePoll(); }
}
async function loadDirectories() {
  try { directories.value = await api<string[]>("/admin/directories"); directoryError.value = ""; }
  catch (e) { directoryError.value = (e as Error).message; }
}
useReviewShortcuts({
  arrowleft: { run: () => move(current.value - 1), enabled: () => current.value > 0 },
  arrowright: { run: () => move(current.value + 1), enabled: () => current.value < images.value.length - 1 },
}, () => !busy.value && !loading.value && !!active.value);
onMounted(() => { void load(); void loadDirectories(); });
onUnmounted(() => { stopped = true; clearTimeout(timer); });
</script>

<template>
  <p class="hint">原图和大图已安排清理，缩略图与审核记录长期保留。可以选择单张或多张恢复；原文件无法获取时，恢复可能失败。</p>
  <div class="trash-actions">
    <n-button :disabled="loading || busy || !images.length" @click="selected = selected.length === images.length ? [] : images.map(image => image.id)">{{ selected.length === images.length && images.length ? '取消全选' : '全选本页' }}</n-button>
    <n-button type="primary" :disabled="loading || busy || !canRestore" :loading="busy" @click="restore">{{ selected.length ? `恢复所选 ${selected.length} 张` : '恢复当前图片' }}</n-button>
    <n-button :disabled="loading || busy" @click="load()">刷新</n-button>
    <span class="muted">共 {{ total }} 张</span>
  </div>
  <label class="field-label trash-directory">从本地目录补回原文件（可选）
    <n-select v-model:value="directory" :disabled="busy" clearable :options="directories.map(value => ({ label: value, value }))" placeholder="自动尝试原位置和帖子来源" aria-label="恢复文件所在目录" />
  </label>
  <n-alert v-if="directoryError" type="warning">本地目录加载失败：{{ directoryError }} <n-button @click="loadDirectories">重试</n-button></n-alert>
  <n-alert v-if="error" type="error">{{ error }} <n-button @click="load()">重试</n-button></n-alert>
  <div class="loading-region" :aria-busy="loading">
    <LoadingOverlay :show="loading" label="正在加载回收站…" />
    <div v-if="!images.length && !error" class="empty-state" :style="{ visibility: loading ? 'hidden' : undefined }"><h2>回收站为空</h2><p>移入回收站的照片会在这里保留缩略图和审核记录</p></div>
    <div v-if="images.length" class="trash-strip" aria-label="回收站图片">
      <div v-for="(image, index) in images" :key="image.id" :class="{ active: index === current }">
        <n-checkbox :checked="selected.includes(image.id)" :disabled="busy || loading" :aria-label="`选择回收站图片 ${image.id}`" @update:checked="$event ? selected.push(image.id) : selected = selected.filter(id => id !== image.id)" />
        <button :disabled="busy || loading" :aria-current="index === current ? 'true' : undefined" :aria-label="`查看回收站图片 ${image.id}`" @click="move(index)"><img :src="`/api/v1/admin/media/${image.id}?thumbnail=true`" alt="" width="72" height="48" loading="lazy" />#{{ image.id }}</button>
      </div>
    </div>
    <div v-if="active" class="trash-detail">
      <div class="trash-heading"><h3>图片 #{{ active.id }}</h3><div class="trash-actions"><n-button :disabled="busy || loading || current === 0" aria-keyshortcuts="ArrowLeft" @click="move(current - 1)">上一张</n-button><span>{{ current + 1 }} / {{ images.length }}</span><n-button :disabled="busy || loading || current === images.length - 1" aria-keyshortcuts="ArrowRight" @click="move(current + 1)">下一张</n-button></div></div>
      <n-alert v-if="active.cleanup_pending" type="warning">部分文件尚未清理，后台会自动重试。</n-alert>
      <n-alert v-if="restoring(active)" type="info">{{ active.restore_task?.stage }} <n-button :disabled="busy" @click="cancel">取消恢复</n-button></n-alert>
      <n-alert v-else-if="active.restore_task?.status === 'failed'" type="error">恢复失败：{{ active.restore_task.error }}。可使用上方恢复按钮重试。</n-alert>
      <p v-else-if="active.restore_task?.status === 'cancelled'" class="hint">恢复已取消，图片仍在回收站。</p>
      <div class="trash-columns">
        <div class="trash-preview">
          <p v-if="failedImages.has(active.id)" class="hint">缩略图不可用，来源与审核记录仍保留。</p>
          <img v-else :key="active.id" :src="`/api/v1/admin/media/${active.id}?thumbnail=true`" :alt="`图片 #${active.id} 的保留缩略图`" :width="active.width" :height="active.height" @error="failedImages.add(active.id)" />
          <p class="hint">保留的缩略图 · {{ active.width }} × {{ active.height }}（原尺寸）</p>
        </div>
        <div class="trash-records">
          <p class="muted">移入时间：{{ dateLabel(active.trashed_at) }} · 重复组 #{{ active.group_id }}</p>
          <section><h3>审核记录</h3><p v-if="!active.faces.length" class="hint">没有人脸记录</p><p v-for="face in active.faces" :key="face.id">人脸 #{{ face.id }} · {{ store.people.find(person => person.id === face.person_id)?.name || '未知人物' }} · {{ face.ignored ? '已忽略' : face.locked ? '已确认' : '待确认' }}</p><p class="hint">关联参考图已暂停使用，恢复成功后重新启用。</p></section>
          <section><h3>来源</h3><p v-if="!active.sources.length" class="hint">没有来源记录</p><div v-for="(source, index) in active.sources" :key="source.id ?? index" class="trash-source"><a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }}</a><span v-else>{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }}</span><p class="hint">{{ dateLabel(source.published_at) }}</p></div></section>
        </div>
      </div>
    </div>
  </div>
  <nav v-if="total > 50" class="trash-actions trash-pagination" aria-label="回收站分页"><n-button :disabled="loading || busy || page <= 1" @click="changePage(page - 1)">上一页</n-button><span>{{ page }} / {{ pages }}</span><n-button :disabled="loading || busy || page >= pages" @click="changePage(page + 1)">下一页</n-button></nav>
</template>

<style scoped>
.trash-actions, .trash-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.trash-heading { justify-content: space-between; }
.trash-directory { display: grid; gap: 8px; max-width: 420px; margin: 16px 0; }
.trash-strip { display: flex; gap: 12px; overflow-x: auto; padding: 8px 0; margin: 16px 0; }
.trash-strip > div { display: flex; align-items: center; flex-shrink: 0; gap: 8px; padding: 4px; border: 1px solid var(--line); border-radius: 4px; }
.trash-strip > .active { border-color: var(--accent); background: var(--selection); }
.trash-strip button { display: grid; justify-items: center; gap: 4px; color: inherit; background: transparent; border: 0; cursor: pointer; }
.trash-strip img { object-fit: contain; }
.trash-detail { display: grid; gap: 16px; }
.trash-columns { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; }
.trash-preview { align-self: start; text-align: center; }
.trash-preview img { display: block; width: auto; height: auto; max-width: 100%; max-height: 65vh; margin: 0 auto; }
.trash-records { min-width: 0; overflow-wrap: anywhere; }
.trash-records section + section { margin-top: 24px; }
.trash-source { border-bottom: 1px solid var(--line); padding: 12px 0; }
.trash-pagination { justify-content: center; margin-top: 24px; font-variant-numeric: tabular-nums; }
@media (min-width: 1200px) { .trash-columns { grid-template-columns: minmax(0, 1fr) 336px; } }
</style>
