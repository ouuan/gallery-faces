<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NButton, NSelect } from 'naive-ui';
import { api } from './api';
import { averageCells } from './face-grid';
import { fromQuery } from './filters';
import { average, formatPoints } from './history-quiz';
import { activityTime, useActivityClock } from './social-time';
import GameFilterSummary from './GameFilterSummary.vue';
import GameRoomRules from './GameRoomRules.vue';
import ListPagination from './ListPagination.vue';
import type { components } from './schema';

type Schema = components['schemas'];
const phases = { lobby: '等待开局', loading: '加载中', answer: '答题中', reveal: '答案揭晓', draft: '填写反馈', vote: '投票中', waiting: '等待出题', finished: '已结束' };
const games = { 'face-game': '认脸游戏', 'history-quiz': '史官测验' };
const options = (map: Record<string, string>) => Object.entries(map).map(([value, label]) => ({ value, label }));
const route = useRoute();
const now = useActivityClock();
const matchId = computed(() => String(route.params.matchId || ''));
const game = ref(''), mode = ref(''), phase = ref(''), page = ref(1), retry = ref(0);
const list = ref<Schema['Matches']>(), detail = ref<Schema['MatchDetail']>(), error = ref('');
watch([game, mode, phase], () => { page.value = 1; });
const query = computed(() => new URLSearchParams({ page: String(page.value), ...(game.value && { game: game.value }),
  ...(mode.value && { mode: mode.value }), ...(phase.value && { phase: phase.value }) }));
watch([query, matchId, retry], async (_, __, cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort());
  error.value = ''; detail.value = undefined; list.value = undefined;
  try {
    if (matchId.value) detail.value = await api(`/admin/game-matches/${encodeURIComponent(matchId.value)}`, { signal: controller.signal });
    else list.value = await api(`/admin/game-matches?${query.value}`, { signal: controller.signal });
  } catch (cause) { if (!controller.signal.aborted) error.value = (cause as Error).message; }
}, { immediate: true });
</script>
<template>
  <div class="matches">
    <router-link v-if="matchId" to="/admin/game-matches">返回对局列表</router-link>
    <div v-else class="match-filters"><label>游戏<n-select v-model:value="game" :options="options({ '': '全部游戏', ...games })" /></label>
      <label>人数模式<n-select v-model:value="mode" :options="options({ '': '全部模式', solo: '单人', multi: '多人' })" /></label>
      <label>状态<n-select v-model:value="phase" :options="options({ '': '全部状态', ...phases })" /></label></div>
    <p v-if="error" role="alert">{{ error }} <n-button @click="retry++">重试</n-button></p>
    <template v-else-if="detail"><h2>{{ games[detail.game] }} · {{ detail.solo ? '单人' : `房间 ${detail.code}` }}</h2>
      <p>{{ phases[detail.phase] }} · 第 {{ detail.round }} 题 · {{ detail.members }} 人</p>
      <GameRoomRules :settings="detail.settings" :history="detail.game === 'history-quiz'" :solo="detail.solo" /><GameFilterSummary :filter="fromQuery(detail.filters)" />
      <h3>玩家成绩</h3>
      <p v-for="member in detail.players" :key="member.name" class="player-result">
        <strong>{{ member.name || '未填写昵称' }}</strong>
        <template v-if="detail.game === 'history-quiz'">
          <span>{{ formatPoints(member.points) }} 分</span><span>平均偏差 {{ average(member.deviation, detail.settled) }}</span>
          <span>已答 {{ detail.settled - member.unanswered }} 题</span>
        </template>
        <template v-else>
          <template v-if="detail.settings.grid">
            <span>{{ member.correct - member.wrong }} 分</span><span>答对时平均 {{ averageCells(member.correct_cells, member.correct) }}</span>
          </template>
          <span v-else>已答 {{ member.correct + member.wrong }} 题</span>
          <span>正确 {{ member.correct }}</span><span>错误 {{ member.wrong }}</span>
        </template>
        <span>未答 {{ member.unanswered }}</span>
      </p>
    </template>
    <template v-else-if="list"><p v-if="!list.total">暂无符合条件的对局</p><table v-else><thead><tr><th>对局</th><th>状态</th><th>最近活动</th></tr></thead><tbody>
      <tr v-for="item in list.items" :key="item.id"><td><router-link :to="`/admin/game-matches/${item.id}`">{{ games[item.game] }} · {{ item.solo ? '单人' : item.code }}</router-link></td><td>{{ phases[item.phase] }} · 第 {{ item.round }} 题</td><td><time :datetime="item.activity">{{ activityTime(item.activity, now) }}</time></td></tr>
    </tbody></table><ListPagination v-if="list.total > 20" :page="page" :page-count="Math.ceil(list.total / 20)" :disabled="false" @change="page = $event" /></template>
    <p v-else role="status">正在读取对局…</p>
  </div>
</template>
<style scoped>
.matches { display: grid; grid-template-columns: minmax(0, 1fr); align-content: start; justify-items: start; gap: 16px; overflow-wrap: anywhere; }
.match-filters { width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 8em), 1fr)); gap: 12px; }
.player-result { display: flex; flex-wrap: wrap; gap: 4px 16px; font-variant-numeric: tabular-nums; }
label { display: grid; gap: 4px; } table { width: 100%; border-collapse: collapse; }
th, td { text-align: start; padding: 8px 4px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; } .matches a { display: inline-flex; align-items: center; min-height: 44px; }
</style>
