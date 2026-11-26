<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowLeft, ArrowRight, Check, X, ZoomIn } from '@lucide/vue';
import { NAlert, NButton } from 'naive-ui';
import { api, ApiError, facePosition, type Photo } from './api';
import { filterOnlyQuery, fromQuery } from './filters';
import { answer, correctChoice, faceZoom, feedbackReceipt, game, openRound, score, type Question } from './face-game';
import { useLibrary } from './store';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import PhotoSidebar from './PhotoSidebar.vue';
import LoadingOverlay from './LoadingOverlay.vue';

const route = useRoute(), store = useLibrary();
const PostDetail = defineAsyncComponent(() => import('./PostDetail.vue'));
const postKey = computed(() => typeof route.query.post === 'string' ? route.query.post : '');
usePageTitle(() => postKey.value ? '帖子详情' : '认脸游戏');
const query = computed(() => filterOnlyQuery(fromQuery(route.query)));
const scope = computed(() => new URLSearchParams(query.value).toString());
const stats = computed(() => score(game.outcomes));
const question = computed(() => game.round?.question);
const answered = computed(() => game.round?.choice !== undefined);
const outcome = computed(() => game.round && game.outcomes[game.round.index]);
const choices = computed(() => [...(question.value?.choices ?? []), { id: null, name: '都不是' }]);
const correctId = computed(() => question.value && correctChoice(question.value));
const submitted = computed(() => game.round ? feedbackReceipt(game.round, game.outcomes) : undefined);
const latest = useLatestRequest(), details = useLatestRequest();
const loading = ref(false), imageReady = ref(false), error = ref(''), empty = ref(false);
const zoomed = ref(false);
function holdZoom(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0 || !imageReady.value) return;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  zoomed.value = true;
}
const imageStyle = computed(() => {
  if (!zoomed.value || !question.value) return;
  const { face, width, height } = question.value;
  const { scale, left, top } = faceZoom(face.box, width, height);
  return { transform: `translate(${left * 100}%, ${top * 100}%) scale(${scale})` };
});
const detail = ref<Photo | null>(null), detailError = ref(''), authenticated = ref(false);
const answerName = computed(() => {
  const personId = question.value?.face.person_id;
  return question.value?.choices.find(choice => choice.id === personId)?.name
    ?? detail.value?.people.find(person => person.id === personId)?.name
    ?? store.people.find(person => person.id === personId)?.name;
});

async function next() {
  const signal = latest.start();
  details.cancel();
  const params = new URLSearchParams(query.value);
  if (question.value) {
    params.set('last_group', String(question.value.group_id));
    params.set('last_face', String(question.value.face.id));
  }
  loading.value = true; empty.value = false; error.value = ''; detail.value = null; detailError.value = '';
  try {
    const result = await api<Question>(`/gallery/face-game?${params}`, { signal });
    if (!signal.aborted) { imageReady.value = false; zoomed.value = false; openRound(result); }
  } catch (cause) {
    if (!signal.aborted) { error.value = (cause as Error).message; empty.value = cause instanceof ApiError && cause.status === 404; }
  } finally { if (!signal.aborted) loading.value = false; }
}

async function loadDetail() {
  const current = question.value;
  if (!current) return;
  const signal = details.start();
  detailError.value = ''; detail.value = null;
  try {
    const result = await api<Photo>(`/gallery/${current.group_id}`, { signal });
    if (result.image_id !== current.image_id) throw new Error('这张照片的代表图已更换');
    if (!signal.aborted) detail.value = result;
  } catch (cause) { if (!signal.aborted) detailError.value = (cause as Error).message; }
}

function choose(person: number | null) {
  if (answered.value || !imageReady.value) return;
  answer(person);
  void loadDetail();
}
watch(scope, value => {
  if (game.filter !== value) { game.filter = value; game.round = null; game.outcomes = []; }
  if (!game.round) void next();
  else if (answered.value) void loadDetail();
}, { immediate: true });
onMounted(() => {
  api<{ admin: boolean }>('/session').then(result => { authenticated.value = result.admin; }).catch(() => {});
  store.load().catch(cause => { detailError.value = (cause as Error).message; });
});
</script>

<template>
  <main class="game-page">
    <header class="game-header"><h1>认脸游戏</h1><router-link :to="{ path: '/', query }"><ArrowLeft :size="16" />返回筛选</router-link></header>
    <div class="game-score" aria-label="本局统计"><strong>正确率 {{ stats.accuracy }}</strong><span>正确 {{ stats.correct }}</span><span>错误 {{ stats.wrong }}</span><span>存疑 {{ stats.disputed }}</span><span>连对 {{ stats.streak }}</span></div>
    <div v-if="error" class="game-status" role="status"><p>{{ error }}</p><n-button v-if="!empty" @click="next">重试</n-button></div>
    <div v-else-if="loading || !question || !game.round" class="game-status"><LoadingOverlay show center label="正在出题…" /></div>
    <div v-else :key="`round:${game.round.key}`" class="game-layout">
      <div class="game-picture">
        <div class="game-frame" :style="{ width: `min(100%, ${question.width}px, ${question.width / question.height * 64}svh)`, aspectRatio: `${question.width} / ${question.height}` }">
          <img :src="question.image_url" :style="imageStyle" alt="题目照片" @load="imageReady = true" @error="error = '照片加载失败，请重试'" />
          <span v-if="imageReady && !zoomed" class="target-face" :style="facePosition(question.face.box, question.width, question.height)" aria-label="要辨认的人脸" />
          <LoadingOverlay :show="!imageReady" center label="正在加载照片…" />
        </div>
      </div>
      <div class="game-controls">
        <div class="game-prompt-row">
          <h2 id="game-prompt">框中的是谁？</h2>
          <n-button quaternary circle :disabled="!imageReady" aria-label="按住放大人脸" title="按住放大人脸"
            @pointerdown="holdZoom" @lostpointercapture="zoomed = false" @contextmenu.prevent
            @keydown.space.enter.prevent="zoomed = true" @keyup.space.enter.prevent="zoomed = false" @blur="zoomed = false">
            <ZoomIn :size="18" aria-hidden="true" />
          </n-button>
        </div>
        <div class="game-options" role="group" aria-labelledby="game-prompt">
          <button v-for="choice in choices" :key="choice.id ?? 'none'" type="button" :disabled="answered || !imageReady"
            :class="{ fallback: choice.id === null, right: answered && choice.id === correctId, wrong: answered && choice.id === game.round.choice && choice.id !== correctId }"
            @click="choose(choice.id)">
            <span>{{ choice.name }}<template v-if="answered && choice.id === null && correctId === null && answerName">（{{ answerName }}）</template></span>
            <Check v-if="answered && choice.id === correctId" :size="16" aria-hidden="true" />
            <X v-else-if="answered && choice.id === game.round.choice" :size="16" aria-hidden="true" />
          </button>
        </div>
        <div class="game-actions">
          <n-button v-if="answered" type="primary" @click="next">下一题 <ArrowRight :size="16" /></n-button>
          <p role="status" :class="{ 'sr-only': outcome !== 'disputed' }">
            <template v-if="outcome === 'disputed'">本题已记为存疑</template>
            <template v-else-if="answered">{{ outcome === 'correct' ? '答对了' : `答错了，你选了${choices.find(choice => choice.id === game.round?.choice)?.name}` }}。图库答案：{{ answerName ?? '都不是' }}</template>
          </p>
        </div>
        <template v-if="answered">
          <PhotoSidebar v-if="detail" inline-post :detail="detail" :authenticated="authenticated" :query="query" :draft-key="`game:${game.round.key}`"
            :feedback-first="outcome === 'wrong' || outcome === 'disputed'"
            :default-face="outcome === 'wrong' ? question.face.id : undefined" :default-person="outcome === 'wrong' ? game.round.choice : null" :submitted="submitted"
            @changed="detail.pending_feedback_count = (detail.pending_feedback_count || 0) + 1" />
          <n-alert v-else-if="detailError" type="error">{{ detailError }} <n-button @click="loadDetail">重试加载详情</n-button></n-alert>
          <div v-else class="detail-loading loading-region"><LoadingOverlay show label="正在加载照片详情…" /></div>
        </template>
      </div>
    </div>
  </main>
  <PostDetail v-if="postKey" :post-key="postKey" return-path="/face-game" />
</template>

<style scoped>
.game-page { max-width: 1440px; margin: auto; padding: 20px 28px; }
.game-header, .game-header a, .game-score { display: flex; align-items: center; }
.game-header { justify-content: space-between; gap: 12px; }
.game-header a { gap: 6px; min-height: 44px; }
.game-score { flex-wrap: wrap; gap: 4px 16px; padding: 8px 0 16px; margin-bottom: 20px; border-bottom: 1px solid var(--line); color: var(--muted); font-variant-numeric: tabular-nums; }
.game-score strong { color: var(--text); }
.game-layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 28px; align-items: start; }
.game-picture { display: grid; place-items: center; }
.game-frame, .game-status { position: relative; }
.game-status { min-height: 200px; text-align: center; }
.game-frame { overflow: hidden; border-radius: 4px; }
.game-frame img { display: block; width: 100%; height: 100%; transform-origin: top left; }
.target-face { position: absolute; border: 3px solid white; outline: 2px solid #222; pointer-events: none; }
.game-controls { min-width: 0; }
.game-prompt-row { display: flex; align-items: center; gap: 4px; }
.game-prompt-row button { width: 44px; height: 44px; touch-action: none; user-select: none; }
.game-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.game-options button {
  display: grid; grid-template-columns: minmax(0, 1fr) 16px; align-items: center; gap: 8px;
  min-height: 44px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--panel); color: var(--text); font-size: 14px; line-height: 1.6; text-align: start; overflow-wrap: anywhere;
}
.game-options .fallback, .game-options button:first-child:nth-last-child(2) { grid-column: 1 / -1; }
.game-options .fallback { background: transparent; color: var(--muted); }
.game-options button:disabled { cursor: default; color: var(--muted); }
@media (hover: hover) { .game-options button:enabled:hover { border-color: var(--accent); color: var(--accent); } }
.game-options button.right { border-color: var(--success); background: var(--success-bg); color: var(--success); }
.game-options button.wrong { border-color: var(--error); color: var(--error); }
.game-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; color: var(--muted); }
.game-actions:has(button) { margin-top: 16px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
.game-controls :deep(.detail-sidebar) { border: 0; border-top: 1px solid var(--line); padding: 16px 0 0; margin-top: 20px; }
@media (max-width: 768px) { .game-page { padding: 12px 16px 24px; } .game-layout { grid-template-columns: minmax(0, 1fr); gap: 16px; } }
</style>
