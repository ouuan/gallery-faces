<script setup lang="ts">
import { computed, onMounted, ref, toRef } from 'vue';
import { NButton } from 'naive-ui';
import { api, ApiError } from './api';
import { useSoloSetup } from './use-solo-setup';
import SoloGameSetup from './SoloGameSetup.vue';
import SoloGameResult from './SoloGameResult.vue';
import SoloGameNav from './SoloGameNav.vue';
import { average, dayLabel, middleDay, session, submit } from './history-quiz';
import { useLatestRequest } from './use-latest-request';
import { usePageTitle } from './page-title';
import HistoryBoard from './HistoryBoard.vue';
import GameRoomSources from './GameRoomSources.vue';

const latest = useLatestRequest();
usePageTitle(() => '史官测验');
const loading = ref(false), error = ref(''), empty = ref(false);
const complete = computed(() => session.roundLimit > 0 && session.count >= session.roundLimit);
async function next() {
  if (complete.value) return end();
  const signal = latest.start(), params = new URLSearchParams(query.value);
  if (session.question) params.set('last_group', String(session.question.group_id));
  loading.value = true; error.value = ''; empty.value = false;
  try {
    const question = await api<NonNullable<typeof session.question>>(`/gallery/history-quiz?${params}`, { signal });
    if (!signal.aborted) Object.assign(session, { question, submitted: false, guess: dayLabel(middleDay(question)) });
  } catch (cause) {
    if (!signal.aborted) { error.value = (cause as Error).message; empty.value = cause instanceof ApiError && cause.status === 404; }
  } finally { if (!signal.aborted) loading.value = false; }
}
const { draft, query, playing, result, start, end } = useSoloSetup(toRef(session, 'scope'), () => {
  latest.cancel(); Object.assign(session, { question: null, guess: '', submitted: false, total: 0, count: 0, early: 0, late: 0 });
}, () => ({ total: session.total, count: session.count, early: session.early, late: session.late }));
async function begin() { if (await start()) void next(); }
onMounted(() => { if (playing.value && !session.question) void next(); });
</script>

<template>
  <main class="quiz-page" :class="{ 'game-start': !playing }">
    <header><h1>史官测验</h1><SoloGameNav rooms-path="/history-quiz/rooms" :query="query" /></header>
    <SoloGameResult v-if="result" :filter="result.filter" :count="result.count" label="平均偏差" :value="result.count ? (result.total / result.count).toFixed(1) : '—'" :unit="result.count ? '天' : undefined" :detail="`累计偏差 ${result.total} 天`"
      :breakdown="[{ label: '猜早', count: result.early, tone: 'amber' }, { label: '正好', count: result.count - result.early - result.late, tone: 'success' }, { label: '猜晚', count: result.late, tone: 'accent' }]" @setup="result = undefined" />
    <SoloGameSetup v-else-if="!playing" v-model="draft" v-model:round-limit="session.roundLimit" @start="begin" />
    <template v-else>
    <div class="score" aria-label="本局统计"><strong>平均偏差 {{ average(session.total, session.count) }}</strong><span>已答 {{ session.count }}<template v-if="session.roundLimit">/{{ session.roundLimit }}</template> 题</span><n-button text @click="end">结束本局</n-button></div>
    <div v-if="error" role="alert">{{ error }} <n-button v-if="!empty" @click="next">重试</n-button></div>
    <HistoryBoard v-else :key="loading ? 'pending' : session.question?.group_id" :photo="loading ? null : session.question" :selected="loading ? null : session.guess" :correct="!loading && session.submitted ? session.question?.correct_date : null"
      @change="session.guess = $event" @choose="submit">
      <template v-if="!loading && session.submitted && session.question"><n-button type="primary" @click="next">{{ complete ? '查看结果' : '下一题' }}</n-button>
        <GameRoomSources :group-id="session.question.group_id" :image-id="session.question.image_id" :query="query" /></template>
    </HistoryBoard>
    </template>
  </main>
</template>

<style scoped>
.quiz-page { width: min(100%, 1440px); margin: auto; padding: 20px 28px 32px; }
header, .score { display: flex; align-items: center; gap: 16px; }
header { justify-content: space-between; flex-wrap: wrap; gap: 0 12px; }
.score { margin-bottom: 12px; padding: 6px 0 10px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.score span { color: var(--muted); }
@media (max-width: 768px) { .quiz-page { padding: 4px 16px 24px; } }
</style>
