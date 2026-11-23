<script setup lang="ts">
import LoadingOverlay from "./LoadingOverlay.vue";
import { ref, watch, computed, nextTick, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  NButton,
  NSelect,
  NDrawer,
  NDrawerContent,
  NModal,
  NAlert,
} from "naive-ui";
import {
  SlidersHorizontal,
  Images,
  X,
  ChevronLeft,
  ChevronRight,
  Download,
  ZoomIn,
  ZoomOut,
  ExternalLink,
  Check,
} from "@lucide/vue";
import { useLibrary } from "./store";
import { usePageTitle } from "./page-title";
import { api, dateLabel, platformLabel, type Photo } from "./api";
import SocialTime from './SocialTime.vue';
import { t } from "./locale";
import { feedHref, hasFilters, clearFilters, emptyFilter, fromQuery, toQuery, type Filter } from "./filters";
import Filters from "./Filters.vue";
import FeedbackPanel from "./FeedbackPanel.vue";
import SourceText from "./SourceText.vue";
import { useMasonry } from "./use-masonry";
import { useImageDownloads } from "./use-review-images";
const store = useLibrary(),
  route = useRoute(),
  router = useRouter();
const postOpen = computed(() => route.name === 'gallery-post');
usePageTitle(() => postOpen.value ? '帖子详情' : '照片库');
const filter = computed(() => fromQuery(route.query)),
  draft = ref(emptyFilter()),
  drawer = ref(false),
  layout = ref(localStorage.getItem("layout") || "justified");
const photos = ref<Photo[]>([]),
  total = ref<number | null>(null),
  cursor = ref<string | null>(null),
  loading = ref(false),
  error = ref(""),
  detail = ref<Photo | null>(null),
  detailError = ref(""),
  zoom = ref(1);
const viewport = ref<HTMLElement | null>(null), photoImage = ref<HTMLImageElement | null>(null);
const drag = ref<{ pointer: number; x: number; y: number; left: number; top: number } | null>(null);

async function zoomTo(value: number, point?: MouseEvent) {
  const frame = viewport.value, image = photoImage.value;
  const scale = Math.max(1, Math.min(3, value));
  if (!frame || !image || scale === zoom.value) return;
  const before = image.getBoundingClientRect(), bounds = frame.getBoundingClientRect();
  if (!before.width || !before.height) return;
  const x = point?.clientX ?? bounds.left + bounds.width / 2;
  const y = point?.clientY ?? bounds.top + bounds.height / 2;
  const fractionX = (x - before.left) / before.width, fractionY = (y - before.top) / before.height;
  zoom.value = scale;
  await nextTick();
  if (frame !== viewport.value || zoom.value !== scale) return;
  const after = image.getBoundingClientRect();
  frame.scrollBy(after.left + fractionX * after.width - x, after.top + fractionY * after.height - y);
}
function wheelZoom(event: WheelEvent) {
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? viewport.value!.clientHeight : 1;
  zoomTo(zoom.value * Math.exp(-event.deltaY * unit * 0.002), event);
}
function startDrag(event: PointerEvent) {
  const frame = viewport.value;
  if (!frame || event.pointerType !== 'mouse' || event.button !== 0 || zoom.value <= 1) return;
  frame.setPointerCapture(event.pointerId);
  drag.value = { pointer: event.pointerId, x: event.clientX, y: event.clientY, left: frame.scrollLeft, top: frame.scrollTop };
}
function pan(event: PointerEvent) {
  const start = drag.value;
  if (start?.pointer === event.pointerId) viewport.value?.scrollTo(start.left + start.x - event.clientX, start.top + start.y - event.clientY);
}
const alternate = (document.getElementById('gallery-rss') as HTMLLinkElement | null) ?? document.createElement('link');
Object.assign(alternate, { id: 'gallery-rss', rel: 'alternate', type: 'application/rss+xml', title: '订阅图库 RSS' });
watch([postOpen, () => feedHref(filter.value)], ([open, href]) => {
  if (open) alternate.remove();
  else { alternate.href = href; document.head.append(alternate); }
}, { immediate: true });
onUnmounted(() => alternate.remove());
const authenticated = ref(false);
const selecting = ref(false),
  downloadSelection = ref(new Set<number>()),
  preparingDownload = ref(false),
  slowPreparation = ref(false),
  downloadError = ref(""),
  downloadNotice = ref("");
const allLoadedSelected = computed(() => photos.value.length > 0 && photos.value.every(photo => downloadSelection.value.has(photo.id)));
function coauthorLabel(coauthor: { username: string; full_name?: string | null }) {
  const name = coauthor.full_name?.trim();
  const username = coauthor.username?.trim();
  return name && username ? `${name} (@${username})` : name || (username ? `@${username}` : "");
}
let downloadController: AbortController | null = null;
function cancelPreparation() {
  downloadController?.abort();
  downloadController = null;
  preparingDownload.value = false;
  slowPreparation.value = false;
}
function stopSelecting() {
  cancelPreparation();
  selecting.value = false;
  downloadSelection.value.clear();
  downloadError.value = "";
  downloadNotice.value = "";
}
function togglePhoto(photo: Photo) {
  if (preparingDownload.value) return;
  if (downloadSelection.value.has(photo.id)) downloadSelection.value.delete(photo.id);
  else downloadSelection.value.add(photo.id);
  downloadError.value = "";
  downloadNotice.value = "";
}
function toggleAllLoaded() {
  if (allLoadedSelected.value) downloadSelection.value.clear();
  else photos.value.forEach(photo => downloadSelection.value.add(photo.id));
  downloadError.value = "";
  downloadNotice.value = "";
}
async function downloadSelected() {
  if (preparingDownload.value || !downloadSelection.value.size || downloadSelection.value.size > 200) return;
  const controller = new AbortController();
  downloadController = controller;
  preparingDownload.value = true;
  const timer = setTimeout(() => {
    if (!controller.signal.aborted) slowPreparation.value = true;
  }, 1000);
  downloadError.value = "";
  downloadNotice.value = "";
  try {
    const result = await api<{ download_url: string; display_count: number; thumbnail_count: number }>("/gallery/downloads", {
      method: "POST",
      body: JSON.stringify({ group_ids: [...downloadSelection.value] }),
      signal: controller.signal,
    });
    if (controller.signal.aborted) return;
    // Let the browser stream to disk instead of buffering the ZIP in a Blob.
    const link = document.createElement("a");
    link.href = result.download_url;
    link.download = "";
    document.body.append(link);
    link.click();
    link.remove();
    const substitutes = [];
    if (result.display_count) substitutes.push(`${result.display_count} 张使用展示图`);
    if (result.thumbnail_count) substitutes.push(`${result.thumbnail_count} 张使用缩略图`);
    downloadNotice.value = substitutes.length ? `已发起下载；准备时有 ${substitutes.join('，')}` : "已发起下载，可在浏览器中查看进度";
  } catch (e) {
    if (!controller.signal.aborted) downloadError.value = (e as Error).message;
  } finally {
    clearTimeout(timer);
    if (downloadController === controller) {
      slowPreparation.value = false;
      preparingDownload.value = false;
      downloadController = null;
    }
  }
}
const photoGrid = ref<HTMLElement | null>(null);
useMasonry(photoGrid, () => layout.value === "masonry", () => photos.value);
let requestVersion = 0,
  detailVersion = 0;
const selectedId = computed(() => !postOpen.value && Number(route.query.photo) || null);
const photoDialogPresent = ref(false);
const { urls: detailImageUrls, failed: failedDetailImages } = useImageDownloads(() =>
  selectedId.value && detail.value?.id === selectedId.value && detail.value.image_url
    ? [{ id: detail.value.image_id, url: detail.value.image_url }] : [],
);
let galleryController: AbortController | null = null;
let detailController: AbortController | null = null;
async function load(more = false) {
  if (more && (loading.value || !cursor.value)) return;
  galleryController?.abort();
  galleryController = new AbortController();
  const version = ++requestVersion;
  if (!more) total.value = null;
  loading.value = true;
  error.value = "";
  try {
    const q = new URLSearchParams(toQuery(filter.value));
    if (more && cursor.value) {
      q.set("cursor", cursor.value);
      q.set("include_total", "false");
    }
    const result = await api<{ items: Photo[]; next_cursor: string | null; total: number | null }>(
      "/gallery?" + q,
      { signal: galleryController.signal },
    );
    if (version !== requestVersion) return;
    photos.value = more ? [...photos.value, ...result.items] : result.items;
    cursor.value = result.next_cursor;
    if (result.total != null) total.value = result.total;
  } catch (e) {
    if (version === requestVersion) error.value = (e as Error).message;
  } finally {
    if (version === requestVersion) loading.value = false;
  }
}
function openFilters() {
  draft.value = JSON.parse(JSON.stringify(filter.value));
  drawer.value = true;
}
function apply(f: Filter) {
  router.push({ query: toQuery(f) });
}
function applyAndCloseFilters() {
  if (!drawer.value) return;
  apply(draft.value);
  drawer.value = false;
}
function open(photo: Photo) {
  router.push({
    query: {
      ...route.query,
      photo: photo.id,
      source: undefined,
    },
  });
}
function close() {
  if (window.history.state?.fromPost) { router.back(); return; }
  const { photo, source, ...query } = route.query;
  router.replace({ query });
}
async function loadDetail() {
  detailController?.abort();
  detailController = new AbortController();
  const version = ++detailVersion;
  detailError.value = "";
  detail.value = null;
  zoom.value = 1;
  drag.value = null;
  if (!selectedId.value) return;
  try {
    const result = await api<Photo>(
      `/gallery/${selectedId.value}`,
      { signal: detailController.signal },
    );
    if (version === detailVersion) detail.value = result;
  } catch (e) {
    if (version === detailVersion) detailError.value = (e as Error).message;
  }
}
const index = computed(() =>
  photos.value.findIndex((p) => p.id === selectedId.value),
);
function move(delta: number) {
  const photo = photos.value[index.value + delta];
  if (photo)
    router.replace({
      query: {
        ...route.query,
        photo: photo.id,
        source: undefined,
      },
    });
}
function keys(event: KeyboardEvent) {
  if (postOpen.value) return;
  if (event.key === "Escape" && selecting.value && !drawer.value && !selectedId.value) {
    stopSelecting();
    return;
  }
  if (
    !selectedId.value ||
    ["INPUT", "TEXTAREA"].includes((event.target as HTMLElement).tagName)
  )
    return;
  if (event.key === "ArrowLeft") move(-1);
  if (event.key === "ArrowRight") move(1);
}
watch(
  () => JSON.stringify(toQuery(filter.value)),
  () => { stopSelecting(); load(); },
  { immediate: true },
);
watch(selectedId, id => {
  if (id) photoDialogPresent.value = true;
  loadDetail();
}, {
  immediate: true,
});
watch(layout, (v) => localStorage.setItem("layout", v));
onMounted(() => {
  api<{ admin: boolean }>("/session")
    .then((session) => (authenticated.value = session.admin === true))
    .catch(() => (authenticated.value = false));
  store.load().catch((e) => (error.value = e.message));
  window.addEventListener("keydown", keys);
});
onUnmounted(() => {
  window.removeEventListener("keydown", keys);
  requestVersion++;
  detailVersion++;
  galleryController?.abort();
  detailController?.abort();
  downloadController?.abort();
});
</script>
<template>
  <main class="gallery-shell">
    <aside class="desktop-filters">
      <Filters
        show-daily
        :model-value="filter"
        @update:model-value="apply"
        @clear="apply(clearFilters(filter))"
      />
    </aside>
    <div class="gallery-content loading-region" :aria-busy="loading">
      <LoadingOverlay :show="loading && !cursor" label="正在加载照片" />
      <div class="gallery-toolbar">
        <div class="gallery-heading">
          <h1>照片库</h1>
          <p class="muted">
            {{
              total == null
                ? "按人物、发布者和日期浏览"
                : `共 ${total} 张照片${cursor ? `，已展示 ${photos.length} 张` : ""}`
            }}
          </p>
        </div>
        <div class="toolbar-actions">
          <div class="gallery-buttons">
            <n-button v-if="!selecting" class="gallery-download" aria-label="下载" title="下载"
              :disabled="!photos.length || loading" @click="selecting = true">
              <Download :size="18" aria-hidden="true" />
              <span class="gallery-download-label">下载</span>
            </n-button>
            <n-button class="mobile-filter" @click="openFilters"
              ><template #icon><SlidersHorizontal /></template>筛选</n-button
            >
          </div>
          <div class="gallery-view-controls">
            <n-select
              aria-label="排序"
              :value="filter.sort"
              :options="[
                { label: '最新发布', value: 'newest' },
                { label: '最早发布', value: 'oldest' },
              ]"
              @update:value="apply({ ...filter, sort: $event })"
            /><n-select
              aria-label="布局"
              v-model:value="layout"
              :options="[
                { label: '等高排列', value: 'justified' },
                { label: '瀑布流', value: 'masonry' },
                { label: '方格', value: 'square' },
              ]"
            />
          </div>
        </div>
      </div>
      <section v-if="selecting" class="gallery-selection" aria-label="批量下载">
        <div class="selection-summary">
          <strong role="status">已选 {{ downloadSelection.size }} 张</strong>
          <span class="hint">优先下载原图；每次最多 200 张</span>
        </div>
        <div class="selection-actions">
          <n-button :disabled="loading || preparingDownload || !photos.length" @click="toggleAllLoaded">
            {{ allLoadedSelected ? '取消全选' : '全选已加载' }}
          </n-button>
          <n-button type="primary" :loading="preparingDownload"
            :disabled="!downloadSelection.size || downloadSelection.size > 200" @click="downloadSelected">
            {{ slowPreparation ? '正在准备 ZIP…' : '下载 ZIP' }}
          </n-button>
          <n-button v-if="preparingDownload" @click="cancelPreparation">取消等待</n-button>
          <n-button v-else @click="stopSelecting">取消</n-button>
        </div>
        <n-alert v-if="downloadError" type="error" title="无法下载" class="selection-feedback">
          {{ downloadError }}
        </n-alert>
        <p v-else-if="downloadNotice" class="hint selection-feedback" role="status">{{ downloadNotice }}</p>
      </section>
      <n-alert v-if="error" type="error" title="无法加载照片"
        >{{ error }}
        <button class="text-button" @click="load()">重试</button></n-alert
      >
      <div v-if="!photos.length && !error" :style="{ visibility: loading ? 'hidden' : undefined }" class="empty-state">
        <Images :size="48" :stroke-width="1" />
        <h2>这里还没有照片</h2>
        <p>调整筛选条件，或在管理工作台导入第一批照片</p>
        <n-button v-if="hasFilters(filter)" @click="apply(clearFilters(filter))">清空筛选</n-button
        ><router-link to="/admin/import">前往导入</router-link>
      </div>
      <div ref="photoGrid" class="photo-grid" :class="layout">
        <button
          v-for="photo in photos"
          :key="photo.id"
          class="photo-card"
          :class="{ 'photo-selected': selecting && downloadSelection.has(photo.id) }"
          :style="{ '--ratio': photo.width / photo.height }"
          @click="selecting ? togglePhoto(photo) : open(photo)"
          :aria-pressed="selecting ? downloadSelection.has(photo.id) : undefined"
          :aria-disabled="selecting && preparingDownload || undefined"
          :aria-label="`${selecting ? '选择' : '查看'} ${photo.people.map((p) => p.name).join('、') || '未知人物'} 的照片`"
        >
          <span class="photo-preview">
          <img
            :src="photo.thumbnail_url"
            :width="photo.width"
            :height="photo.height"
            alt=""
            loading="lazy"
          />
          <span v-if="selecting" class="photo-selection-mark" aria-hidden="true">
            <Check v-if="downloadSelection.has(photo.id)" :size="20" />
          </span>
          </span><span class="photo-meta"
            ><strong>{{
              photo.people.map((p) => p.name).join(" · ") || "未知人物"
            }}</strong
            ><span
              >{{ store.publisherName(photo.matched_source) }} ·
              <SocialTime :value="photo.matched_source.published_at" in-card :disabled="photoDialogPresent || postOpen || drawer" /></span
            ><span v-if="photo.source_count > 1"
              >{{ photo.source_count }} 个来源</span
            ></span
          >
        </button>
      </div>
      <div class="load-more" role="status" aria-live="polite">
        <n-button class="stable-loading-button"
          v-if="cursor" :loading="loading"
          @click="load(true)"
          >加载更多</n-button
        >
      </div>
    </div>
  </main>
  <n-drawer
    :show="drawer"
    placement="left"
    width="min(340px, 100vw)"
    aria-label="筛选照片"
    @update:show="!$event && applyAndCloseFilters()"
    ><n-drawer-content
      ><Filters v-model="draft" show-daily @clear="draft = clearFilters(draft)" /><template
        #footer
        ><n-button
          type="primary"
          block
          @click="applyAndCloseFilters"
          >应用筛选</n-button
        ></template
      ></n-drawer-content
    ></n-drawer
  >
  <n-modal
    :show="!!selectedId"
    @after-leave="photoDialogPresent = false"
    @update:show="!$event && close()"
    :auto-focus="true"
    ><div
      class="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label="照片详情"
    >
      <div class="lightbox-tools">
        <div class="lightbox-tool-group" role="group" aria-label="切换图片">
          <n-button aria-label="上一张" :disabled="index <= 0" @click="move(-1)">
            <ChevronLeft />
          </n-button>
          <n-button
            aria-label="下一张"
            :disabled="index < 0 || index >= photos.length - 1"
            @click="move(1)"
          ><ChevronRight /></n-button>
        </div>
        <div class="lightbox-tool-group" role="group" aria-label="图片操作">
          <n-button aria-label="缩小" :disabled="zoom <= 1" @click="zoomTo(zoom - 0.25)">
            <ZoomOut />
          </n-button>
          <n-button aria-label="放大" :disabled="!detail || zoom >= 3" @click="zoomTo(zoom + 0.25)">
            <ZoomIn />
          </n-button>
          <a
            v-if="detail"
            class="icon-link"
            :href="detail.download_url"
            aria-label="下载原图"
          ><Download /></a>
        </div>
        <n-button class="close-detail" aria-label="关闭详情" @click="close"><X /></n-button>
      </div>
      <n-alert v-if="detailError" type="error"
        >{{ detailError }}<n-button @click="loadDetail">重试</n-button></n-alert
      >
      <div v-else-if="detail" class="detail-body">
        <div ref="viewport" class="detail-image loading-region" :class="{ zoomed: zoom > 1, dragging: drag }"
          :aria-busy="!detailImageUrls.has(detail.image_id) && !failedDetailImages.has(detail.image_id)"
          @wheel.prevent="wheelZoom" @dblclick="zoomTo(zoom > 1 ? 1 : 2, $event)"
          @pointerdown="startDrag" @pointermove="pan" @lostpointercapture="drag = null">
          <img
            ref="photoImage"
            :key="detail.image_id"
            :src="!failedDetailImages.has(detail.image_id) && detailImageUrls.get(detail.image_id) || detail.thumbnail_url"
            :style="{
              width: `calc(min(${detail.width}px, 100cqw, ${100 * detail.width / detail.height}cqh) * ${zoom})`,
              aspectRatio: `${detail.width} / ${detail.height}`,
            }"
            alt="当前照片"
            draggable="false"
            @error="detailImageUrls.has(detail.image_id) && failedDetailImages.add(detail.image_id)"
          />
          <LoadingOverlay :show="failedDetailImages.has(detail.image_id) || !detailImageUrls.has(detail.image_id)" center :error="failedDetailImages.has(detail.image_id)" :label="failedDetailImages.has(detail.image_id) ? '图片加载失败' : '正在加载图片…'" />
        </div>
        <aside class="detail-sidebar">
          <header class="detail-summary">
            <h2>{{ detail.people.map((p) => p.name).join("、") || "未知人物" }}</h2>
            <div v-if="authenticated" class="detail-manage-actions">
              <router-link class="detail-manage" :to="{ path: '/admin/review', query: { state: 'image', image: detail.image_id } }">管理此图片</router-link>
              <router-link class="detail-manage" :to="{ path: '/admin/duplicates', query: { image: detail.image_id } }">审核重复图片</router-link>
            </div>
          </header>
          <section class="detail-sources" aria-label="图片来源">
            <h2 class="detail-sources-heading">来源 · {{ detail.source_count }}</h2>
            <div v-for="source in detail.sources" :key="source.id" class="source-block">
              <header class="source-header">
                <h3>
                  <router-link class="source-title-link" :to="{ path: '/posts/' + (source.key ?? `${source.platform}:record:${source.id}`), query: toQuery(filter), state: { fromPhoto: true } }">
                    <span>{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }}</span>
                  </router-link><a class="icon-link" :href="source.url" target="_blank" rel="noopener noreferrer" title="打开原帖" aria-label="打开原帖"><ExternalLink :size="16" aria-hidden="true" /></a>
                </h3>
                <div class="source-meta">
                  <time :datetime="source.published_at">{{ dateLabel(source.published_at) }}</time>
                  <span v-if="source.images?.length" class="source-resolution">
                    <span aria-hidden="true">·</span>
                    <span>{{ [...new Set(source.images.map(image => image.width + " × " + image.height))].join("、") }}</span>
                  </span>
                </div>
                <div v-if="source.coauthors?.length" class="source-coauthors">
                  <strong>{{ t("共同作者") }}</strong>
                  <span>{{ source.coauthors.map(coauthorLabel).filter(Boolean).join("、") }}</span>
                </div>
              </header>
              <SourceText :text="source.post_text" />
            </div>
          </section>
          <FeedbackPanel :key="detail.image_id" :image-id="detail.image_id" :pending-count="detail.pending_feedback_count" @changed="detail.pending_feedback_count = (detail.pending_feedback_count || 0) + 1" />
        </aside>
      </div>
      <div v-else class="detail-loading loading-region" aria-busy="true"><LoadingOverlay show center label="正在加载照片详情" /></div></div
  ></n-modal>
  <router-view />
</template>
