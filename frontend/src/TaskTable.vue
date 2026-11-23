<script lang="ts">
export const taskKindLabels: Record<string, string> = {
  avatar: "发布者头像",
  monitor: "发布者监控", download: "链接下载", import: "目录导入", detect: "人脸检测", rematch: "人物匹配", restore: "图片恢复",
};
export const taskStatusLabels: Record<string, string> = {
  queued: "排队中", running: "执行中", done: "已完成", failed: "失败", cancelled: "已取消",
};
export interface TaskRecord {
  id: number; kind: string; status: string; stage: string; image_id?: number;
  payload: { url?: string; directory?: string; start?: string; end?: string; hashtags?: string[]; mode?: string; refresh_all?: boolean };
  result: { imported?: number; skipped_existing?: number; skipped_trashed?: number };
  done: number; total: number; speed: number; rounds?: number; cancel_requested?: number;
  created_at?: string; started_at?: string | null; round_started_at?: string | null; finished_at?: string; error?: string;
  elapsed_seconds?: number | null; round_seconds?: number | null;
}
</script>

<script setup lang="ts">
import { ref } from "vue";
import { ChevronRight } from "@lucide/vue";
import { NButton } from "naive-ui";
import { dateLabel } from "./api";
import { formatHashtags } from "./HashtagField.vue";

defineProps<{ tasks: TaskRecord[]; loading: boolean }>();
defineEmits<{ action: [id: number, action: 'cancel' | 'retry'] }>();
const expanded = ref<number | null>(null);
const finishLabels: Record<string, string> = { done: '完成时间', failed: '失败时间', cancelled: '取消时间' };
function title(task: TaskRecord) {
  if (task.kind === 'monitor' && task.payload.mode === 'backfill') return '历史补采';
  if (task.kind === 'monitor' && task.payload.mode === 'incremental') return '增量检查';
  if (task.kind === 'detect' && task.payload.mode === 'highres') return '高分辨率人脸检测';
  if (task.kind === 'rematch') return task.payload.refresh_all ? '重新匹配全部人脸' : '匹配未知人脸';
  return taskKindLabels[task.kind] || task.kind;
}
function target(task: TaskRecord) {
  return task.image_id ? `图片 #${task.image_id}` : task.payload.url || task.payload.directory;
}
function stage(task: TaskRecord) {
  const parts = [];
  if (['running', 'queued'].includes(task.status) && !task.cancel_requested && task.stage &&
      ![task.status, taskStatusLabels[task.status], '等待处理'].includes(task.stage)) parts.push(task.stage);
  if (task.rounds) parts.push(`第 ${task.rounds} 轮`);
  return parts.join(' · ');
}
function progress(task: TaskRecord) {
  const unit = task.kind === 'rematch' ? '个人脸' : '张';
  if (task.total > 0) return `${task.done} / ${task.total} ${unit}`;
  if (task.done > 0 || task.status === 'done') return `已处理 ${task.done} ${unit}`;
  return '';
}
function outcome(task: TaskRecord) {
  const { imported, skipped_existing = 0, skipped_trashed = 0 } = task.result;
  if (imported == null || (!imported && !skipped_existing && !skipped_trashed && task.status !== 'done')) return '';
  return [`新入库 ${imported} 张`, ...(skipped_existing + skipped_trashed ? [`跳过 ${skipped_existing + skipped_trashed} 张`] : [])].join(' · ');
}
function speed(task: TaskRecord) {
  return `${task.speed < 0.1 ? '<0.1' : task.speed.toFixed(1)} ${task.kind === 'rematch' ? '个人脸' : '张'}/秒`;
}
function duration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  if (minutes >= 60) return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
  return minutes ? `${minutes} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}
</script>

<template>
  <table class="task-table" aria-label="任务记录" :aria-busy="loading">
    <thead><tr><th>任务 / 对象</th><th>状态</th><th title="不含排队等待时间">运行时长</th><th>进度 / 结果</th><th>操作</th></tr></thead>
    <tbody v-for="task in tasks" :key="task.id">
      <tr class="record">
        <td class="identity">
          <button type="button" class="disclosure" :aria-expanded="expanded === task.id" :aria-controls="`task-detail-${task.id}`"
            :aria-label="`${expanded === task.id ? '收起' : '展开'}任务 #${task.id} 详情：${title(task)} ${target(task) || ''}`" @click="expanded = expanded === task.id ? null : task.id">
            <ChevronRight :size="16" aria-hidden="true" />
            <span class="identity-copy"><span class="task-name">{{ title(task) }} <small>#{{ task.id }}</small></span>
              <span v-if="target(task)" class="secondary truncate">{{ target(task) }}</span>
            </span>
          </button>
        </td>
        <td class="state" :data-status="task.status">
          <span>{{ task.cancel_requested && task.status === 'running' ? '正在取消' : taskStatusLabels[task.status] }}</span>
          <span v-if="stage(task)" class="secondary">{{ stage(task) }}</span>
        </td>
        <td class="runtime" :title="task.round_started_at ? `第 ${task.rounds} 轮开始：${dateLabel(task.round_started_at)}` : task.started_at ? `任务开始：${dateLabel(task.started_at)}` : undefined">
          <span v-if="task.round_seconds != null">本轮 {{ duration(task.round_seconds) }}</span>
          <span v-if="task.elapsed_seconds != null && (task.round_seconds == null || (task.rounds || 0) > 1)" :class="{ secondary: task.round_seconds != null }">{{ task.rounds && task.rounds > 1 ? '累计' : '已运行' }} {{ duration(task.elapsed_seconds) }}</span>
        </td>
        <td class="summary">
          <span>{{ outcome(task) || progress(task) }}</span>
          <span v-if="task.error" class="error-preview truncate">{{ task.error.split('\n', 1)[0] }}</span>
          <span v-else-if="task.status === 'running' && task.speed > 0" class="secondary">{{ speed(task) }}</span>
        </td>
        <td class="actions">
          <n-button v-if="['queued', 'running'].includes(task.status)" :disabled="loading || !!task.cancel_requested" @click="$emit('action', task.id, 'cancel')">取消</n-button>
          <n-button v-else-if="['failed', 'cancelled'].includes(task.status)" :disabled="loading" @click="$emit('action', task.id, 'retry')">重试</n-button>
        </td>
      </tr>
      <tr v-if="expanded === task.id" :id="`task-detail-${task.id}`" class="detail-row"><td colspan="5">
        <div class="detail">
          <span v-if="task.payload.url || task.payload.directory">{{ task.payload.url ? '链接' : '目录' }}：{{ task.payload.url || task.payload.directory }}</span>
          <span v-if="task.payload.hashtags?.length">标签：{{ formatHashtags(task.payload.hashtags) }}</span>
          <span v-if="task.payload.start || task.payload.end">{{ task.kind === 'import' ? '导入范围' : '下载范围' }}：<template v-if="task.payload.start && !task.payload.end">自 </template><time v-if="task.payload.start" :datetime="task.payload.start">{{ dateLabel(task.payload.start) }}</time><template v-else>截至 </template><template v-if="task.payload.start && task.payload.end"> 至 </template><template v-if="task.payload.end"><time :datetime="task.payload.end">{{ dateLabel(task.payload.end) }}</time>（不含）</template><template v-else> 起</template></span>
          <div class="facts">
            <span v-if="task.created_at">创建时间：<time :datetime="task.created_at">{{ dateLabel(task.created_at) }}</time></span>
            <span v-if="task.started_at">任务开始：<time :datetime="task.started_at">{{ dateLabel(task.started_at) }}</time></span>
            <span v-if="task.round_started_at">第 {{ task.rounds }} 轮开始：<time :datetime="task.round_started_at">{{ dateLabel(task.round_started_at) }}</time></span>
            <span v-if="task.finished_at && finishLabels[task.status]">{{ finishLabels[task.status] }}：<time :datetime="task.finished_at">{{ dateLabel(task.finished_at) }}</time></span>
          </div>
          <div class="facts">
            <span v-if="progress(task)">进度：{{ progress(task) }}</span>
            <span v-if="task.result.skipped_existing">跳过已收录 {{ task.result.skipped_existing }} 张</span>
            <span v-if="task.result.skipped_trashed">跳过回收站 {{ task.result.skipped_trashed }} 张</span>
          </div>
          <span v-if="task.error" class="error-text">{{ task.error }}</span>
        </div>
      </td></tr>
    </tbody>
  </table>
</template>

<style scoped>
.task-table { table-layout: fixed; margin-top: 16px; }
th:first-child { width: 31%; }
th:nth-child(2) { width: 17%; }
th:nth-child(3) { width: 19%; }
th:last-child { width: 76px; }
.record td { padding-block: 8px; vertical-align: middle; }
.actions, th:last-child { text-align: right; }
.disclosure { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 44px; text-align: left; background: transparent; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; }
.disclosure svg { flex: none; color: var(--muted); }
.disclosure[aria-expanded=true] svg { transform: rotate(90deg); }
.disclosure:hover .task-name { color: var(--accent); }
.identity-copy { min-width: 0; }
.task-name { font-weight: 600; }
small, .secondary { color: var(--muted); font-size: 12px; font-weight: 400; }
small { margin-inline-start: 4px; white-space: nowrap; }
.secondary, .error-preview { display: block; }
.truncate { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.state[data-status=running] > :first-child { color: var(--accent); }
.state[data-status=failed], .error-preview { color: var(--error); }
.error-preview { font-size: 12px; }
.detail-row td { background: var(--panel); padding: 12px; }
.detail { display: grid; gap: 4px; overflow-wrap: anywhere; font-size: 13px; }
.facts { display: flex; flex-wrap: wrap; gap: 4px 20px; }
.facts:empty { display: none; }
@media (max-width: 700px) {
  .task-table, tbody { display: block; }
  thead { position: absolute; clip-path: inset(50%); width: 1px; height: 1px; overflow: hidden; }
  .record { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'identity state' 'runtime actions' 'summary actions'; gap: 0 12px; align-items: center; border-bottom: 1px solid var(--line); padding: 8px 0; }
  .record td { padding: 0; width: auto; border: 0; }
  .identity { grid-area: identity; }
  .state { grid-area: state; text-align: right; }
  .runtime { grid-area: runtime; display: flex; align-items: baseline; flex-wrap: wrap; column-gap: 8px; }
  .summary { grid-area: summary; }
  .actions { grid-area: actions; }
  .record .runtime, .record .summary { padding-inline-start: 24px; }
  .summary { color: var(--muted); font-size: 13px; }
  .detail-row, .detail-row td { display: block; width: auto; }
}
</style>
