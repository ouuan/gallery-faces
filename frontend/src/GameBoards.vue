<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NButton } from 'naive-ui';
import { api } from './api';
import { filterOnlyQuery, fromQuery } from './filters';
import { parseRules, ruleQuery } from './game-rules';
import GameFilterSummary from './GameFilterSummary.vue';
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
    <p v-if="error" role="alert">{{ error }} <n-button @click="retry++">重试</n-button></p>
    <template v-else-if="detail"><h2>{{ label(detail.board) }}</h2><GameFilterSummary :filter="fromQuery(detail.board.filters)" />
      <router-link :to="{ path, query: boardQuery(detail.board) }">按此规则开局</router-link>
      <table v-if="detail.records.length"><thead><tr><th>名次</th><th>昵称</th><th>成绩</th><th>上榜时间</th></tr></thead>
      <tbody><tr v-for="record in detail.records" :key="record.nickname"><td>{{ record.rank }}</td><th scope="row">{{ record.nickname }}</th>
        <td>{{ history ? `平均偏差 ${(record.deviation / record.rounds).toFixed(1)} 天` : `${record.correct} 题` }}<template v-if="!history && detail.board.settings.grid && record.correct"> · 平均 {{ (record.cells / record.correct).toFixed(1) }} 格</template></td>
        <td><time :datetime="record.recorded_at">{{ new Date(record.recorded_at).toLocaleString() }}</time></td></tr></tbody></table><p v-else>暂无上榜成绩</p>
    </template>
    <template v-else-if="boards"><p v-if="!boards.length">暂无榜单</p><article v-for="board in boards" :key="board.id">
      <h2><router-link :to="{ path: path + '/boards/current', query: boardQuery(board) }">{{ label(board) }}</router-link></h2><span>{{ board.members }} 人上榜</span>
      <GameFilterSummary :filter="fromQuery(board.filters)" /><router-link :to="{ path, query: boardQuery(board) }">按此规则开局</router-link></article></template>
    <p v-else role="status">正在读取榜单…</p>
  </main>
</template>
<style scoped>
.boards { max-width: 960px; margin: auto; padding: 16px clamp(12px, 3vw, 28px); }
header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
h2 { font-size: 1.1rem; } article { border-bottom: 1px solid var(--line); padding-block: 12px; }
a { display: inline-flex; min-height: 44px; align-items: center; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
td, th { border-bottom: 1px solid var(--line); text-align: start; padding: 10px 4px; overflow-wrap: anywhere; }
</style>
