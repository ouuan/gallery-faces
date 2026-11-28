<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NSelect } from 'naive-ui';
import { RefreshCw } from '@lucide/vue';
import { api, dateLabel } from './api';
import { faceAccuracy } from './face-game';
import { averageCells } from './face-grid';
import { fromQuery } from './filters';
import { average, formatPoints } from './history-quiz';
import { activityTime } from './social-time';
import GameFilterSummary from './GameFilterSummary.vue';
import GameRoomRules from './GameRoomRules.vue';
import ListPagination from './ListPagination.vue';
import type { components } from './schema';

type Schema = components['schemas'];
const phases = { lobby: '等待开局', loading: '加载中', answer: '答题中', reveal: '答案揭晓', draft: '填写反馈', vote: '投票中', waiting: '等待出题', finished: '已结束' };
const games = { 'face-game': '认脸游戏', 'history-quiz': '史官测验' };
const modes = { solo: '单人', multi: '多人' };
const statuses = { lobby: phases.lobby, active: '进行中', finished: phases.finished };
const options = (map: Record<string, string>) => Object.entries(map).map(([value, label]) => ({ value, label }));
const route = useRoute();
const router = useRouter();
const loadedAt = ref(0);
const matchId = computed(() => String(route.params.matchId || ''));
function filterParam(key: string, choices: Record<string, string>) {
  return computed({ get() {
    const value = route.query[key];
    return typeof value === 'string' && Object.hasOwn(choices, value) ? value : '';
  }, set(value: string) { void router.push({ query: { ...route.query, [key]: value || undefined, page: undefined } }); } });
}
const game = filterParam('game', games), mode = filterParam('mode', modes), phase = filterParam('phase', statuses);
const page = computed(() => {
  const value = Number(route.query.page);
  return Number.isInteger(value) && value >= 1 && value <= 1_000_000 ? value : 1;
});
const refresh = ref(0), loading = ref(false);
const list = ref<Schema['Matches']>(), detail = ref<Schema['MatchDetail']>(), error = ref('');
const query = computed(() => new URLSearchParams({ page: String(page.value), ...(game.value && { game: game.value }),
  ...(mode.value && { mode: mode.value }), ...(phase.value && { phase: phase.value }) }));
const endpoint = computed(() => matchId.value ? `/admin/game-matches/${encodeURIComponent(matchId.value)}` : `/admin/game-matches?${query.value}`);
watch([endpoint, refresh], async ([path], [previousPath], cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort());
  if (path !== previousPath) { detail.value = undefined; list.value = undefined; }
  error.value = ''; loading.value = true;
  try {
    if (matchId.value) detail.value = await api(path, { signal: controller.signal });
    else {
      list.value = await api(path, { signal: controller.signal });
      loadedAt.value = Date.now();
    }
  } catch (cause) { if (!controller.signal.aborted) error.value = (cause as Error).message; }
  finally { if (!controller.signal.aborted) loading.value = false; }
}, { immediate: true });
</script>
<template>
  <div class="matches">
    <router-link v-if="matchId" :to="{ path: '/admin/game-matches', query: route.query }">返回对局列表</router-link>
    <div v-else class="match-filters"><label>游戏<n-select v-model:value="game" :options="options({ '': '全部游戏', ...games })" /></label>
      <label>人数模式<n-select v-model:value="mode" :options="options({ '': '全部模式', ...modes })" /></label>
      <label>状态<n-select v-model:value="phase" :options="options({ '': '全部状态', ...statuses })" /></label>
      <n-button :loading="loading" :disabled="loading" @click="refresh++"><template #icon><RefreshCw aria-hidden="true" /></template>刷新</n-button></div>
    <p v-if="error" role="alert">{{ error }} <n-button v-if="matchId" @click="refresh++">重试</n-button></p>
    <template v-if="detail"><h2>{{ games[detail.game] }} · {{ detail.solo ? '单人' : `房间 ${detail.code}` }}</h2>
      <p>{{ phases[detail.phase] }} · 第 {{ detail.round }} 题 · {{ detail.members }} 人</p>
      <p class="match-times"><span>创建时间：<time v-if="detail.created_at" :datetime="detail.created_at">{{ dateLabel(detail.created_at) }}</time><template v-else>未记录</template></span>
        <span>最后活动时间：<time :datetime="detail.activity">{{ dateLabel(detail.activity) }}</time></span></p>
      <GameRoomRules :settings="detail.settings" :history="detail.game === 'history-quiz'" :solo="detail.solo" /><GameFilterSummary :filter="fromQuery(detail.filters)" />
      <h3>玩家成绩</h3>
      <p v-for="member in detail.players" :key="member.name" class="player-result">
        <strong>{{ member.name || '未填写昵称' }}</strong>
        <template v-if="detail.game === 'history-quiz'">
          <span v-if="!detail.solo">{{ formatPoints(member.points) }} 分</span><span>平均偏差 {{ average(member.deviation, detail.settled) }}</span>
          <span>已答 {{ detail.settled - member.unanswered }} 题</span>
        </template>
        <template v-else>
          <template v-if="detail.solo">
            <span>正确率 {{ faceAccuracy(member.correct, member.wrong, member.disputed) }}</span><span>已答 {{ member.correct + member.wrong }} 题</span>
            <span>正确 {{ member.correct }}</span><span>错误 {{ member.wrong - member.disputed }}</span><span>存疑 {{ member.disputed }}</span>
          </template>
          <template v-else-if="detail.settings.single_life && !detail.settings.grid">
            <span>已通过 {{ member.correct }} 题</span><span>{{ member.eliminated ? '已淘汰' : '存活' }}</span>
          </template>
          <template v-else>
            <span v-if="detail.settings.grid">{{ member.correct - member.wrong }} 分</span>
            <span v-else>正确率 {{ faceAccuracy(member.correct, member.wrong) }}</span>
            <span>正确 {{ member.correct }}</span><span>错误 {{ member.wrong }}</span>
          </template>
          <span v-if="detail.settings.grid">答对时平均 {{ averageCells(member.correct_cells, member.correct) }}</span>
        </template>
        <span>未答 {{ member.unanswered }}</span>
      </p>
    </template>
    <template v-else-if="list"><p v-if="!list.total">暂无符合条件的对局</p><table v-else><thead><tr><th>对局</th><th>状态</th><th>最近活动</th></tr></thead><tbody>
      <tr v-for="item in list.items" :key="item.id"><td><router-link :to="{ path: `/admin/game-matches/${item.id}`, query: route.query }">{{ games[item.game] }} · {{ item.solo ? '单人' : item.code }}</router-link></td><td>{{ phases[item.phase] }} · 第 {{ item.round }} 题</td><td><time :datetime="item.activity">{{ activityTime(item.activity, loadedAt) }}</time></td></tr>
    </tbody></table><ListPagination v-if="list.total > 20" :page="page" :page-count="Math.ceil(list.total / 20)" :disabled="false" @change="router.push({ query: { ...route.query, page: $event === 1 ? undefined : $event } })" /></template>
    <p v-else-if="loading" role="status">正在读取对局…</p>
  </div>
</template>
<style scoped>
.matches { display: grid; grid-template-columns: minmax(0, 1fr); align-content: start; justify-items: start; gap: 16px; overflow-wrap: anywhere; }
.match-filters { width: 100%; display: flex; align-items: end; flex-wrap: wrap; gap: 12px; }
.match-filters label { flex: 1 1 8em; min-width: 0; }
.match-times, .player-result { display: flex; flex-wrap: wrap; gap: 4px 16px; font-variant-numeric: tabular-nums; }
label { display: grid; gap: 4px; } table { width: 100%; border-collapse: collapse; }
th, td { text-align: start; padding: 8px 4px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; } .matches a { display: inline-flex; align-items: center; min-height: 44px; }
</style>
