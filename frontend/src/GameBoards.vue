<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NButton } from 'naive-ui';
import { api } from './api';
import { filterOnlyQuery, fromQuery } from './filters';
import { parseRules, ruleQuery } from './game-rules';
import GameFilterSummary from './GameFilterSummary.vue';
import GameBoardRecords from './GameBoardRecords.vue';
import { usePageTitle } from './page-title';
import type { components } from './schema';

type Board = components['schemas']['Board'];
const route = useRoute();
const game = computed(() => String(route.params.game)), path = computed(() => '/' + game.value);
const history = computed(() => game.value === 'history-quiz');
const filter = computed(() => fromQuery(route.query)), settings = computed(() => parseRules(route.query, history.value));
const scope = computed(() => String(route.params.scope)), rules = computed(() => ruleQuery(settings.value, filter.value, history.value));
const labels: Record<string, string> = { current: '当前榜单', filters: '当前筛选的榜单', all: '全部榜单' };
const title = computed(() => `${history.value ? '史官测验' : '认脸游戏'} · ${labels[scope.value]}`);
usePageTitle(() => title.value);
const detail = ref<components['schemas']['BoardView']>(), boards = ref<Board[]>(), error = ref(''), retry = ref(0);
watch([() => route.fullPath, retry], async (_, __, cleanup) => {
  const controller = new AbortController(); cleanup(() => controller.abort());
  detail.value = undefined; boards.value = undefined; error.value = '';
  const body = { settings: settings.value, filters: { ...filterOnlyQuery(filter.value), include_no_faces: filter.value.include_no_faces } };
  const options = { method: 'POST', body: JSON.stringify(body), signal: controller.signal };
  try {
    if (scope.value === 'current') detail.value = await api(`${path.value}/boards/current`, options);
    else boards.value = await api(`${path.value}/boards/list?scope=${scope.value}`, options);
  } catch (cause) { if (!controller.signal.aborted) error.value = (cause as Error).message; }
}, { immediate: true });
const boardQuery = (board: Board) => ruleQuery(board.settings, fromQuery(board.filters), history.value);
function label(board: Board) {
  const rules = board.settings;
  const mode = rules.single_life ? '一命' : rules.round_limit ? `固定 ${rules.round_limit} 题` : '无尽';
  const display = history.value ? '' : ` · ${rules.cropped ? '仅截取人脸' : '全图'} · ${rules.grid ? `逐格 ${rules.grid_size}×${rules.grid_size}（${rules.grid_seconds} 秒）` : '直接显示'}`;
  return `${mode} · 每题 ${rules.answer_seconds} 秒${display}`;
}
</script>
<template>
  <main class="boards"><header><h1>{{ title }}</h1><router-link :to="{ path, query: rules }">返回游戏</router-link></header>
    <GameFilterSummary v-if="scope === 'filters'" class="scope-filter" :filter="filter" />
    <p v-if="error" role="alert">{{ error }} <n-button @click="retry++">重试</n-button></p>
    <template v-else-if="detail"><div class="board-row"><div class="board-info"><h2>{{ label(detail.board) }}</h2><GameFilterSummary :filter="fromQuery(detail.board.filters)" /></div>
      <router-link :to="{ path, query: boardQuery(detail.board) }">按此规则开局</router-link></div>
      <GameBoardRecords :board="detail" />
    </template>
    <template v-else-if="boards"><p v-if="!boards.length">暂无榜单</p><div v-else><article v-for="board in boards" :key="board.id" class="board-row">
      <div class="board-info"><h2><router-link :to="{ path: path + '/boards/current', query: boardQuery(board) }">{{ label(board) }}</router-link></h2>
        <GameFilterSummary v-if="scope === 'all'" :filter="fromQuery(board.filters)" /></div>
      <div class="board-actions"><span>{{ board.members }} 人上榜</span><router-link :to="{ path, query: boardQuery(board) }">按此规则开局</router-link></div></article></div></template>
    <p v-else role="status">正在读取榜单…</p>
  </main>
</template>
<style scoped>
.boards { width: min(100%, 960px); margin-inline: auto; padding: 20px 28px 40px; display: grid; align-content: start; gap: 20px; }
header, .board-row, .board-actions { display: flex; align-items: baseline; justify-content: space-between; gap: 0 16px; flex-wrap: wrap; }
header, article, .scope-filter { border-bottom: 1px solid var(--line); }
.scope-filter { padding-bottom: 16px; }
article { padding-block: 8px 12px; }
.board-info { flex: 1 1 24rem; min-width: 0; display: grid; gap: 8px; }
.board-actions { align-items: center; }
.board-actions span { color: var(--muted); }
h2 { font-size: 1.1rem; }
a { display: inline-flex; min-height: 44px; align-items: center; }
@media (max-width: 599px) {
  .boards { padding: 8px 16px 28px; gap: 16px; }
  .board-actions { width: 100%; }
}
</style>
