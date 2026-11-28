<script setup lang="ts">
import { dateLabel } from './api';
import type { components } from './schema';

defineProps<{ board: components['schemas']['BoardView']; limit?: number }>();
</script>

<template>
  <table v-if="board.records.length" aria-label="公开榜单成绩">
    <thead><tr><th scope="col">名次</th><th scope="col">昵称</th><th scope="col">成绩</th><th v-if="!limit" scope="col">上榜时间</th></tr></thead>
    <tbody><tr v-for="entry in board.records.slice(0, limit)" :key="entry.nickname">
      <td class="place">{{ entry.rank }}</td><th scope="row">{{ entry.nickname }}</th>
      <td>{{ board.board.game === 'history-quiz' ? `平均偏差 ${(entry.deviation / entry.rounds).toFixed(1)} 天` : `${entry.correct} 题` }}<template v-if="board.board.settings.grid && entry.correct"> · 平均 {{ (entry.cells / entry.correct).toFixed(1) }} 格</template></td>
      <td v-if="!limit"><time :datetime="entry.recorded_at">{{ dateLabel(entry.recorded_at).replace(' ', '\n') }}</time></td>
    </tr></tbody>
  </table>
  <p v-else class="empty">暂无上榜成绩</p>
</template>

<style scoped>
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { text-align: start; border-bottom: 1px solid var(--line); padding: 10px 8px; overflow-wrap: anywhere; }
thead th, time, .empty { color: var(--muted); }
thead th { font-weight: 500; white-space: nowrap; }
th:first-child, .place { width: 4em; padding-inline-start: 0; }
td:last-child, th:last-child { text-align: end; padding-inline-end: 0; }
time { font-size: .875rem; white-space: nowrap; }
@media (max-width: 599px) {
  th, td { padding-inline: 4px; }
  time { display: inline-block; white-space: pre; }
}
</style>
