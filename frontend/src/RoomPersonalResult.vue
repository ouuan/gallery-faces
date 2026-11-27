<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { average } from './history-quiz';
import type { RoomView } from './use-game-room';

const props = defineProps<{ room: RoomView; player: RoomView['players'][number]; rank: number | null; tied: boolean }>();
const answered = computed(() => props.player.correct + props.player.wrong);
const totalDeviation = computed(() => props.room.history?.total_deviations[props.player.id] ?? 0);
const heading = ref<HTMLElement | null>(null);
onMounted(() => {
  heading.value?.focus({ preventScroll: true });
  window.scrollTo(0, 0);
});
</script>

<template>
  <section class="personal-result" role="group" aria-labelledby="my-result-title">
    <h2 id="my-result-title" ref="heading" tabindex="-1">我的战绩</h2>
    <div class="personal-score">
      <div class="place"><strong v-if="rank">{{ tied ? '并列第' : '第' }} {{ rank }} 名</strong><strong v-else>暂无名次</strong><span>共 {{ room.players.length }} 位玩家</span></div>
      <div class="measures">
        <template v-if="room.history"><strong>平均偏差 {{ average(totalDeviation, room.history.settled) }}</strong>
          <div><span>累计偏差 {{ totalDeviation }} 天</span><span>已答 {{ room.history.settled - player.unanswered }} 题</span><span>未答 {{ player.unanswered }} 题</span></div>
          <small v-if="player.unanswered">未答按居中日期计分</small></template>
        <template v-else><strong v-if="room.settings.single_life">已通过 {{ player.correct }} 题 · {{ player.eliminated ? '已淘汰' : '存活' }}</strong>
          <strong v-else>答对 {{ player.correct }} 题</strong>
          <div><span v-if="!room.settings.single_life">正确率 {{ answered ? `${Math.round(100 * player.correct / answered)}%` : '—' }}</span><span>错误 {{ player.wrong }} 题</span><span>未答 {{ player.unanswered }} 题</span></div></template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.personal-result { padding: 20px 0 24px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
h2 { margin: 0 0 12px; }
.personal-score { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 48px; }
.place, .measures { display: grid; gap: 4px; }
.place strong { font-size: 2rem; line-height: 1.25; }
.place span, .measures div, small { color: var(--muted); }
.measures strong { font-size: 1.15rem; }
.measures div { display: flex; flex-wrap: wrap; gap: 4px 16px; }
</style>
