<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ArrowLeft, ArrowRight } from '@lucide/vue';
import { NAlert, NButton, NSwitch } from 'naive-ui';
import { api, ApiError, type Photo } from './api';
import { filterOnlyQuery, fromQuery } from './filters';
import { answer, correctChoice, feedbackReceipt, game, openRound, score, type Question } from './face-game';
import { useLibrary } from './store';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import GameBoard from './GameBoard.vue';
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
const loading = ref(false), error = ref(''), empty = ref(false);
const cropped = ref(localStorage.getItem('face-game:cropped') === 'true');
watch(cropped, value => localStorage.setItem('face-game:cropped', String(value)));
const photo = computed(() => !loading.value && !error.value && question.value ? { ...question.value, box: question.value.face.box } : null);
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
    if (!signal.aborted) openRound(result);
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
  if (answered.value) return;
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
    <header class="game-header"><h1>认脸游戏</h1><nav><router-link :to="{ path: '/face-game/rooms', query }">多人对战</router-link><router-link :to="{ path: '/', query }" aria-label="返回筛选" title="返回筛选"><ArrowLeft :size="16" /><span>返回筛选</span></router-link></nav></header>
    <div class="game-score" aria-label="本局统计"><strong>正确率 {{ stats.accuracy }}</strong><span>正确 {{ stats.correct }}</span><span>错误 {{ stats.wrong }}</span><span>存疑 {{ stats.disputed }}</span><span>连对 {{ stats.streak }}</span></div>
    <GameBoard :key="game.round?.key" :photo="photo" :cropped="cropped" :revealed="answered" :locked="answered" :selected="game.round?.choice" :correct-id="correctId" :answer-name="answerName" @choose="choose">
      <template #placeholder>
        <div v-if="error" role="status"><p>{{ error }}</p><n-button v-if="!empty" @click="next">重试</n-button></div>
        <LoadingOverlay v-else show center label="正在出题…" />
      </template>
      <template #mode><label class="crop-mode"><n-switch v-model:value="cropped" size="small" aria-label="截取人脸" />截取人脸</label></template>
      <template v-if="question && game.round">
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
      </template>
    </GameBoard>
  </main>
  <PostDetail v-if="postKey" :post-key="postKey" return-path="/face-game" />
</template>

<style scoped>
.game-page { width: min(100%, 1440px); margin: auto; padding: 20px 28px; }
.game-header, .game-header a, .game-score { display: flex; align-items: center; }
.game-header { justify-content: space-between; gap: 12px; }
.game-header a { gap: 6px; min-height: 44px; }
.game-score { flex-wrap: wrap; gap: 4px 16px; padding: 8px 0 16px; margin-bottom: 20px; border-bottom: 1px solid var(--line); color: var(--muted); font-variant-numeric: tabular-nums; }
.game-header nav, .crop-mode { display: flex; align-items: center; gap: 12px; }
.crop-mode { margin-inline-start: auto; min-height: 44px; gap: 6px; color: var(--muted); }
.game-header a { justify-content: center; min-width: 44px; }
.game-score strong { color: var(--text); }
.game-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; color: var(--muted); }
.game-actions:has(button) { margin-top: 16px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
:deep(.detail-sidebar) { border: 0; border-top: 1px solid var(--line); padding: 16px 0 0; margin-top: 20px; }
@media (max-width: 768px) {
  .game-page { padding: 4px 16px 24px; }
  .game-score { gap: 4px 12px; padding: 0 0 8px; margin-bottom: 8px; }
  .game-actions:has(button) { margin-top: 8px; }
  .game-actions button { flex: 1; }
  .game-header a span { display: none; }
}
@media (min-width: 600px) and (orientation: landscape) and (max-height: 540px) {
  .game-page { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 8px 20px; padding: 4px 16px 16px; }
  .game-score { justify-content: end; gap: 4px 12px; margin: 0; padding: 0; border: 0; }
  .game-page > .game-layout { grid-column: 1 / -1; }
}
</style>
