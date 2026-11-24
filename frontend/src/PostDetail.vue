<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { X, ExternalLink, UserRound } from '@lucide/vue';
import { NAlert, NButton, NModal, NTooltip } from 'naive-ui';
import { api, ApiError, platformLabel } from './api';
import { toQuery, fromQuery, publisherRoute } from './filters';
import type { components } from './schema';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import SocialTime from './SocialTime.vue';
import LoadingOverlay from './LoadingOverlay.vue';

const props = defineProps<{ postKey: string }>();
const route = useRoute(), router = useRouter();
const filters = computed(() => toQuery(fromQuery(route.query)));
function close() {
  if (window.history.state?.fromPhoto) router.back();
  else router.replace({ path: '/', query: filters.value });
}
const post = ref<components['schemas']['PostDetail'] | null>(null);
const unavailableTip = ref<number | null>(null);
const textParts = computed(() => {
  const text = post.value?.post_text ?? '';
  return text.split(/(https?:\/\/[^\s<>]+|(?<![\p{L}\p{M}\p{N}_])#[\p{L}\p{M}\p{N}_]+)/gu).map((label, index) => {
    if (index % 2 === 0) return { label };
    if (!label.startsWith('#')) return { label, href: label };
    const tag = encodeURIComponent(label.slice(1));
    return { label, href: post.value?.platform === 'x' ? `https://x.com/hashtag/${tag}` : `https://www.instagram.com/explore/tags/${tag}/` };
  });
});
const error = ref(''), missing = ref(false), avatar = ref<string | null>(null);
const latest = useLatestRequest();
usePageTitle(() => post.value ? `@${post.value.author} 的帖子` : '帖子详情');
async function load() {
  const signal = latest.start();
  unavailableTip.value = null;
  error.value = ''; missing.value = false; post.value = null;
  try {
    const result = await api<components['schemas']['PostDetail']>('/posts/' + encodeURIComponent(props.postKey), { signal });
    if (!signal.aborted) post.value = result;
  } catch (cause) {
    if (!signal.aborted) {
      error.value = (cause as Error).message;
      missing.value = cause instanceof ApiError && cause.status === 404;
    }
  }
}
watch(() => props.postKey, load, { immediate: true });
watch(post, (current, _, cleanup) => {
  avatar.value = null;
  if (!current) return;
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>, delay = 2000;
  async function update() {
    try {
      const state = await api<components['schemas']['PublisherAvatar']>(`/publisher-avatars/${current!.platform}/${encodeURIComponent(current!.author)}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      avatar.value = state.image_url;
      if (state.pending) {
        timer = setTimeout(update, delay);
        delay = Math.min(60_000, delay * 2);
      }
    } catch { return; }
  }
  void update();
  cleanup(() => { controller.abort(); clearTimeout(timer); });
});
</script>

<template>
  <n-modal :show="true" @update:show="!$event && close()">
  <div class="post-dialog" role="dialog" aria-modal="true" aria-labelledby="post-dialog-title">
    <header class="post-toolbar"><h2 id="post-dialog-title">帖子详情</h2>
      <n-button quaternary circle title="关闭帖子详情" aria-label="关闭帖子详情" @click="close"><X :size="20" /></n-button>
    </header>
    <div class="post-scroll">
    <n-alert v-if="error" type="error">{{ error }} <n-button v-if="!missing" @click="load">重试</n-button></n-alert>
    <article v-else-if="post" class="post">
      <router-link class="post-avatar" :to="publisherRoute(post.platform, post.author)" :aria-label="`查看 @${post.author} 发布的照片`">
        <img v-if="avatar" :src="avatar" alt="" @error="avatar = null" /><UserRound v-else :size="22" aria-hidden="true" />
      </router-link>
      <div class="post-content">
      <header class="post-header">
        <h3><router-link class="post-author" :to="publisherRoute(post.platform, post.author)" :title="`查看 @${post.author} 发布的照片`">
          <strong v-if="post.author_name">{{ post.author_name }}</strong><span :class="{ handle: post.author_name }">@{{ post.author }}</span>
        </router-link></h3>
        <span class="post-dot" aria-hidden="true">·</span><SocialTime :value="post.published_at" />
        <a class="icon-link post-external" :href="post.url" target="_blank" rel="noopener noreferrer" :aria-label="`打开 ${platformLabel(post.platform)} 原帖`" title="打开原帖"><ExternalLink :size="18" /></a>
      </header>
      <p v-if="post.coauthors.length" class="coauthors">共同作者：{{ post.coauthors.map(person => '@' + person.username).join('、') }}</p>
      <p v-if="post.post_text" class="post-copy"><template v-for="(part, index) in textParts" :key="index"><a v-if="part.href" :href="part.href" target="_blank" rel="noopener noreferrer">{{ part.label }}</a><template v-else>{{ part.label }}</template></template></p>
      <div v-if="post.images.length" class="post-pictures" :class="{ single: post.images.length === 1, 'triple-tail': post.images.length >= 3 && post.images.length % 2 === 1 }">
        <template v-for="(picture, index) in post.images" :key="picture.id">
        <router-link v-if="picture.image_url !== null" class="post-tile" :to="{ path: '/', query: { ...filters, photo: picture.id }, state: { fromPost: true } }">
          <img :src="post.images.length === 1 ? picture.image_url : picture.thumbnail_url" :width="picture.width" :height="picture.height" :loading="index < 4 ? 'eager' : 'lazy'" :alt="`查看照片 ${index + 1}${picture.people.length ? '：' + picture.people.map(person => person.name).join('、') : ''}`" />
        </router-link>
        <n-tooltip v-else trigger="manual" :show="unavailableTip === picture.id" :animated="false" @clickoutside="unavailableTip = null">
          <template #trigger>
            <span class="post-tile unavailable" tabindex="0" role="group" :aria-label="`照片 ${index + 1}`" :aria-describedby="unavailableTip === picture.id ? 'post-unavailable-tip' : undefined"
              @pointerenter="$event.pointerType === 'mouse' && (unavailableTip = picture.id)" @pointerleave="$event.pointerType === 'mouse' && (unavailableTip = null)"
              @click="unavailableTip = picture.id" @focus="unavailableTip = picture.id" @blur="unavailableTip = null" @keydown.esc="unavailableTip = null">
              <button type="button" disabled :aria-label="`照片 ${index + 1}，图片无法查看`"><img :src="picture.thumbnail_url" :width="picture.width" :height="picture.height" :loading="index < 4 ? 'eager' : 'lazy'" alt="" /></button>
            </span>
          </template>
          <span id="post-unavailable-tip" role="tooltip">图片无法查看</span>
        </n-tooltip>
        </template>
      </div>
      </div>
    </article>
    <div v-else class="post-loading loading-region" aria-busy="true"><LoadingOverlay show center label="正在加载帖子" /></div>
    </div>
  </div>
  </n-modal>
</template>

<style scoped>
.post-dialog { display: flex; flex-direction: column; width: min(620px, calc(100vw - 48px)); max-height: calc(100dvh - 48px); overflow: hidden; background: var(--panel); color: var(--text); border-radius: 8px; }
.post-toolbar { display: flex; flex: none; justify-content: space-between; align-items: center; padding: 6px 12px 6px 20px; border-bottom: 1px solid var(--line); }
.post-toolbar h2 { font-size: 18px; }
.post-scroll { overflow: auto; overscroll-behavior: contain; padding: 20px; }
.post { display: grid; grid-template-columns: 44px minmax(0, 1fr); align-items: start; gap: 10px; }
.post-author, .post-header { display: flex; align-items: baseline; gap: 4px; }
.post-header { position: relative; min-height: 24px; padding-inline-end: 36px; color: var(--muted); font-size: 14px; line-height: 1.4; white-space: nowrap; }
.post-header h3 { min-width: 0; font-size: 16px; }
.post-author { color: var(--text); }
.post-author > strong, .post-author > span:last-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.post-author .handle { color: var(--muted); font-size: 14px; font-weight: 400; }
.post-avatar { background: var(--panel); border: 1px solid var(--line); border-radius: 50%; width: 44px; height: 44px; flex: none; display: grid; place-items: center; overflow: hidden; }
.post-avatar img { width: 100%; height: 100%; object-fit: cover; }
.post-external { position: absolute; inset: -10px -8px auto auto; color: var(--muted); }
.coauthors { color: var(--muted); font-size: 13px; margin-top: 8px; overflow-wrap: anywhere; }
.post-copy { white-space: pre-wrap; overflow-wrap: anywhere; margin-top: 2px; font-size: 16px; line-height: 1.5; }
.post-pictures { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px; margin-top: 12px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.post-tile { display: block; aspect-ratio: 1; min-height: 0; overflow: hidden; background: var(--bg); }
.post-tile.unavailable { cursor: not-allowed; }
.unavailable button { display: block; width: 100%; height: 100%; padding: 0; border: 0; background: transparent; pointer-events: none; }
.post-pictures.triple-tail { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.triple-tail .post-tile { grid-column: span 3; }
.triple-tail .post-tile:nth-last-child(-n + 3) { grid-column: span 2; }
.post-tile:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.post-pictures img { width: 100%; height: 100%; display: block; object-fit: cover; }
.post-pictures.single { grid-template-columns: minmax(0, 1fr); }
.single .post-tile { aspect-ratio: auto; }
.single img { height: auto; max-height: min(60dvh, 560px); object-fit: contain; }
.post-loading { min-height: 240px; }
@media (max-width: 768px) {
  .post-dialog { width: 100vw; height: 100dvh; max-height: none; border-radius: 0; }
  .post-toolbar { padding: max(6px, env(safe-area-inset-top)) max(8px, env(safe-area-inset-right)) 6px max(16px, env(safe-area-inset-left)); }
  .post-scroll { padding: 16px max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left)); }
}
</style>
