<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  NButton,
  NSelect,
  NDrawer,
  NDrawerContent,
  NModal,
  NAlert,
  NSpin,
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
} from "@lucide/vue";
import { useLibrary } from "./store";
import { usePageTitle } from "./page-title";
import { api, dateLabel, platformLabel, type Photo } from "./api";
import { hasFilters, clearFilters, emptyFilter, fromQuery, toQuery, type Filter } from "./filters";
import Filters from "./Filters.vue";
import FeedbackPanel from "./FeedbackPanel.vue";
import SourceText from "./SourceText.vue";
import { useMasonry } from "./use-masonry";
usePageTitle("照片库");
const store = useLibrary(),
  route = useRoute(),
  router = useRouter();
const filter = computed(() => fromQuery(route.query)),
  draft = ref(emptyFilter()),
  drawer = ref(false),
  layout = ref(localStorage.getItem("layout") || "justified");
const photos = ref<Photo[]>([]),
  cursor = ref<string | null>(null),
  loading = ref(false),
  error = ref(""),
  detail = ref<Photo | null>(null),
  detailError = ref(""),
  zoom = ref(1);
const authenticated = ref(false);
const photoGrid = ref<HTMLElement | null>(null);
useMasonry(photoGrid, () => layout.value === "masonry", () => photos.value);
let requestVersion = 0,
  detailVersion = 0,
  lastFocus: HTMLElement | null = null;
const selectedId = computed(() => Number(route.query.photo) || null);
let galleryController: AbortController | null = null;
let detailController: AbortController | null = null;
async function load(more = false) {
  if (more && (loading.value || !cursor.value)) return;
  galleryController?.abort();
  galleryController = new AbortController();
  const version = ++requestVersion;
  loading.value = true;
  error.value = "";
  try {
    const q = new URLSearchParams(toQuery(filter.value));
    if (more && cursor.value) q.set("cursor", cursor.value);
    const result = await api<{ items: Photo[]; next_cursor: string | null }>(
      "/gallery?" + q,
      { signal: galleryController.signal },
    );
    if (version !== requestVersion) return;
    photos.value = more ? [...photos.value, ...result.items] : result.items;
    cursor.value = result.next_cursor;
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
  lastFocus = document.activeElement as HTMLElement;
  router.push({
    query: {
      ...route.query,
      photo: photo.id,
      source: undefined,
    },
  });
}
function close() {
  const { photo, source, ...query } = route.query;
  router.replace({ query });
  nextTick(() => lastFocus?.focus());
}
async function loadDetail() {
  detailController?.abort();
  detailController = new AbortController();
  const version = ++detailVersion;
  detailError.value = "";
  detail.value = null;
  zoom.value = 1;
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
  if (
    !selectedId.value ||
    ["INPUT", "TEXTAREA"].includes((event.target as HTMLElement).tagName)
  )
    return;
  if (event.key === "ArrowLeft") move(-1);
  if (event.key === "ArrowRight") move(1);
  if (event.key === "Escape") close();
}
watch(
  () => JSON.stringify(toQuery(filter.value)),
  () => load(),
  { immediate: true },
);
watch(selectedId, loadDetail, {
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
});
</script>
<template>
  <main class="gallery-shell">
    <aside class="desktop-filters">
      <Filters
        :model-value="filter"
        @update:model-value="apply"
        @clear="apply(clearFilters(filter))"
      />
    </aside>
    <div class="gallery-content">
      <div class="gallery-toolbar">
        <div>
          <h1>照片库</h1>
          <p class="muted">
            {{
              photos.length
                ? `已展示 ${photos.length} 组照片`
                : "按人物、发布者和日期浏览"
            }}
          </p>
        </div>
        <div class="toolbar-actions">
          <n-button class="mobile-filter" @click="openFilters"
            ><template #icon><SlidersHorizontal /></template>筛选</n-button
          ><n-select
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
      <n-alert v-if="error" type="error" title="无法加载照片"
        >{{ error }}
        <button class="text-button" @click="load()">重试</button></n-alert
      >
      <div v-if="!loading && !photos.length && !error" class="empty-state">
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
          :style="{ '--ratio': photo.width / photo.height }"
          @click="open(photo)"
          :aria-label="`查看 ${photo.people.map((p) => p.name).join('、') || '未知人物'} 的照片`"
        >
          <img
            :src="photo.thumbnail_url"
            :width="photo.width"
            :height="photo.height"
            alt=""
            loading="lazy"
          /><span class="photo-meta"
            ><strong>{{
              photo.people.map((p) => p.name).join(" · ") || "未知人物"
            }}</strong
            ><span
              >{{ store.publisherName(photo.matched_source) }} ·
              {{ dateLabel(photo.matched_source.published_at) }}</span
            ><span v-if="photo.source_count > 1"
              >{{ photo.source_count }} 个来源</span
            ></span
          >
        </button>
      </div>
      <div class="load-more" role="status" aria-live="polite">
        <n-spin v-if="loading" aria-label="正在加载照片" /><n-button
          v-else-if="cursor"
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
      ><Filters v-model="draft" @clear="draft = clearFilters(draft)" /><template
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
          <n-button aria-label="缩小" :disabled="zoom <= 1" @click="zoom = Math.max(1, zoom - 0.25)">
            <ZoomOut />
          </n-button>
          <n-button aria-label="放大" :disabled="zoom >= 3" @click="zoom += 0.25">
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
        <div class="detail-image">
          <img
            :src="detail.image_url"
            :style="{
              width: zoom === 1 ? 'auto' : `${zoom * 100}%`,
              maxWidth: zoom === 1 ? '100%' : 'none',
              maxHeight: zoom === 1 ? '100%' : 'none',
            }"
            alt="当前照片"
          />
        </div>
        <aside class="detail-sidebar">
          <header class="detail-summary">
            <h2>{{ detail.people.map((p) => p.name).join("、") || "未知人物" }}</h2>
            <router-link
              v-if="authenticated"
              class="detail-manage"
              :to="{ path: '/admin/review', query: { state: 'image', image: detail.image_id } }"
              >管理此图片</router-link>
          </header>
          <section class="detail-sources" aria-label="图片来源">
            <h2 class="detail-sources-heading">来源 · {{ detail.source_count }}</h2>
            <div v-for="source in detail.sources" :key="source.id" class="source-block">
              <header class="source-header">
                <h3>
                  <a class="source-title-link" :href="source.url" target="_blank" rel="noopener noreferrer">
                    <span>{{ platformLabel(source.platform) }} · {{ store.publisherName(source) }}</span>
                    <ExternalLink :size="14" aria-hidden="true" />
                  </a>
                </h3>
                <div class="source-meta">
                  <time :datetime="source.published_at">{{ dateLabel(source.published_at) }}</time>
                  <span v-if="source.images?.length" class="source-resolution">
                    <span aria-hidden="true">·</span>
                    <span>{{ [...new Set(source.images.map(image => image.width + " × " + image.height))].join("、") }}</span>
                  </span>
                </div>
              </header>
              <SourceText :text="source.post_text" />
            </div>
          </section>
          <FeedbackPanel :key="detail.image_id" :image-id="detail.image_id" :pending-count="detail.pending_feedback_count" @changed="detail.pending_feedback_count = (detail.pending_feedback_count || 0) + 1" />
        </aside>
      </div>
      <div v-else class="empty-state" role="status" aria-label="正在加载照片详情"><n-spin /></div></div
  ></n-modal>
</template>
