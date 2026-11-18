<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { NButton, NInput, NInputNumber, NSelect, NCheckbox, NModal, NCard, NAlert } from "naive-ui";
import { api, send, dateLabel, platformLabel } from "./api";
import LocalDateTime from "./LocalDateTime.vue";
import DateRangeHint from "./DateRangeHint.vue";
import type { components } from "./schema";
type Monitor = components["schemas"]["Monitor"];
const items = ref<Monitor[]>([]), selected = ref<number[]>([]), error = ref(""), busy = ref(false), loading = ref(false);
const intervals = ref<Record<number, number | null>>({});
const platform = ref("instagram"), username = ref(""), interval = ref(60), start = ref(""), history = ref(false);
const candidates = ref<{ label: string; value: string }[]>([]);
const dialog = ref<"delete" | "backfill" | "resume" | null>(null), targets = ref<number[]>([]), since = ref(""), mode = ref("catch_up");
const results = ref<{ id: number; status: string; task_id?: number; error?: string }[]>([]);
const all = computed(() => items.value.length > 0 && selected.value.length === items.value.length);
const dialogTitle = computed(() => dialog.value === "delete" ? "删除 " + targets.value.length + " 项监控" : dialog.value === "resume" ? "恢复监控" : "补齐 " + targets.value.length + " 位发布者");
const validSince = computed(() => !!since.value && Date.parse(since.value) < Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
let searchVersion = 0;
async function load() {
  loading.value = true;
  try {
    items.value = await api<Monitor[]>("/admin/monitors");
    selected.value = selected.value.filter(id => items.value.some(item => item.id === id));
  } catch (e) { error.value = (e as Error).message; }
  finally { loading.value = false; }
}
async function search(q = "") {
  const version = ++searchVersion;
  try {
    const rows = await api<{ platform: string; username: string; label: string }[]>("/admin/publisher-candidates?q=" + encodeURIComponent(q));
    if (version === searchVersion) candidates.value = rows.map(row => ({ value: row.platform + ":" + row.username, label: row.label + " · " + platformLabel(row.platform) + " @" + row.username }));
  } catch (e) { error.value = (e as Error).message; }
}
function choose(value: string | null) {
  if (value) [platform.value, username.value] = value.split(":") as [string, string];
}
async function perform(action: () => Promise<unknown>) {
  busy.value = true; error.value = "";
  try { await action(); await load(); }
  catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function create() {
  await perform(async () => {
    await send("/admin/monitors", { platform: platform.value, username: username.value, interval_minutes: interval.value, start: history.value ? start.value : "" });
    username.value = ""; start.value = ""; history.value = false;
  });
}
function open(action: "delete" | "backfill" | "resume", ids: number[]) {
  error.value = ""; targets.value = [...ids]; since.value = ""; mode.value = "catch_up"; dialog.value = action;
}
async function batch(action: "delete" | "backfill" | "update", ids: number[]) {
  await perform(async () => {
    results.value = await send("/admin/monitors/batch", { action, ids, start: since.value });
    dialog.value = null;
  });
}
async function confirm() {
  if (dialog.value === "resume") {
    await perform(async () => {
      await send("/admin/monitors/" + targets.value[0] + "/resume", { mode: mode.value, start: since.value });
      dialog.value = null;
    });
  } else if (dialog.value) await batch(dialog.value, targets.value);
}
function toggle(id: number, checked: boolean) {
  selected.value = checked ? [...selected.value, id] : selected.value.filter(value => value !== id);
}
function resultLabel(raw: string | null) {
  const result = JSON.parse(raw || "{}");
  return "imported" in result ? `新入库 ${result.imported} · 跳过已收录 ${result.skipped_existing} · 跳过回收站 ${result.skipped_trashed}` : "暂无导入结果";
}
onMounted(() => { void load(); void search(); timer = setInterval(() => { if (!busy.value && !loading.value) void load(); }, 5000); });
onUnmounted(() => { clearInterval(timer); ++searchVersion; });
</script>
<template>
  <div class="monitor-manager">
    <n-alert v-if="error" type="error">{{ error }}</n-alert>
    <form class="monitor-create" @submit.prevent="create">
      <h2>添加发布者</h2>
      <label class="field-label">搜索人物账号或来源发布者
        <n-select :value="null" filterable remote clearable :options="candidates" placeholder="搜索人物、昵称或用户名" @search="search" @update:value="choose" />
      </label>
      <div class="monitor-fields">
        <label class="field-label">平台<n-select v-model:value="platform" :options="[{ label: 'Instagram', value: 'instagram' }, { label: 'X', value: 'x' }]" /></label>
        <label class="field-label">用户名<n-input v-model:value="username" placeholder="用户名，不含 @" /></label>
        <label class="field-label">检查间隔（分钟）<n-input-number v-model:value="interval" :min="5" :precision="0" /></label>
      </div>
      <n-checkbox v-model:checked="history">指定起始时间，补拉历史</n-checkbox>
      <label v-if="history" class="field-label">起始时间<LocalDateTime aria-label="起始时间" v-model="start" /></label>
      <DateRangeHint v-if="history" :start="start" end="" />
      <p v-else class="hint">默认只收新增，以保存时刻为起点。</p>
      <n-button type="primary" attr-type="submit" :loading="busy" :disabled="busy || !username.trim() || !interval || (history && !start)">添加监控</n-button>
    </form>
    <div class="monitor-toolbar">
      <n-checkbox :checked="all" :indeterminate="selected.length > 0 && !all" @update:checked="selected = $event ? items.map(item => item.id) : []">全选当前列表</n-checkbox>
      <span v-if="selected.length">已选 {{ selected.length }} 项</span>
      <template v-if="selected.length">
        <n-button :disabled="busy" @click="batch('update', selected)">立刻更新</n-button>
        <n-button :disabled="busy" @click="open('backfill', selected)">补齐</n-button>
        <n-button :disabled="busy" @click="open('delete', selected)">删除</n-button>
      </template>
      <n-button :loading="loading" @click="load">刷新</n-button>
      <router-link to="/admin/import?kind=monitor">查看监控任务</router-link>
    </div>
    <div v-if="results.length" role="status">
      <p v-for="result in results" :key="result.id" :class="{ 'error-text': result.error }">
        #{{ result.id }}：{{ result.error || (result.status === 'deleted' ? '已删除监控，已导入照片保留' : '任务 #' + result.task_id + ' 已提交或复用') }}
      </p>
    </div>
    <p v-if="!items.length && !loading" class="hint">还没有发布者监控。添加后会立即检查，并按设定间隔收集新增照片。</p>
    <ul class="monitor-list" :aria-busy="loading">
      <li v-for="item in items" :key="item.id">
        <div class="monitor-toolbar">
          <n-checkbox :aria-label="'选择 ' + item.username" :checked="selected.includes(item.id)" @update:checked="toggle(item.id, $event)" />
          <strong>{{ platformLabel(item.platform) }} @{{ item.username }}</strong>
          <span>{{ item.paused ? (item.active_task_id ? '已暂停，等待任务结束' : '已暂停') : item.active_task_id ? '检查中' : '监控中' }}</span>
        </div>
        <div class="monitor-fields">
          <label class="field-label">检查间隔（分钟）
            <n-input-number  :value="intervals[item.id] ?? item.interval_minutes" @update:value="intervals[item.id] = $event" :min="5" :precision="0" />
          </label>
          <n-button :disabled="busy || intervals[item.id] === null" @click="perform(() => send('/admin/monitors/' + item.id, { interval_minutes: intervals[item.id] ?? item.interval_minutes }, 'PATCH'))">保存间隔</n-button>
        </div>
        <p class="hint">上次检查：{{ item.last_checked_at ? dateLabel(item.last_checked_at) : '尚未检查' }} · 下次检查：{{ item.paused ? '已暂停' : dateLabel(item.next_check_at) }}</p>
        <p class="hint">{{ resultLabel(item.last_result) }}<template v-if="item.last_status"> · {{ ({ done: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[item.last_status] || item.last_status }}</template></p>
        <p v-if="item.last_error" class="error-text">{{ item.last_error }}</p>
        <div class="monitor-toolbar">
          <n-button v-if="!item.paused" :disabled="busy" @click="perform(() => send('/admin/monitors/' + item.id, { paused: true }, 'PATCH'))">暂停</n-button>
          <n-button v-else :disabled="busy || !!item.active_task_id" @click="open('resume', [item.id])">恢复</n-button>
          <n-button :disabled="busy" @click="batch('update', [item.id])">立刻更新</n-button>
          <n-button :disabled="busy" @click="open('backfill', [item.id])">补齐</n-button>
          <n-button :disabled="busy" @click="open('delete', [item.id])">删除</n-button>
        </div>
      </li>
    </ul>
    <n-modal :show="!!dialog" :mask-closable="!busy" @update:show="!busy && !$event && (dialog = null)">
      <n-card class="monitor-dialog" role="dialog" aria-modal="true" :title="dialogTitle" :aria-label="dialogTitle">
        <n-alert v-if="error" type="error">{{ error }}</n-alert>
        <p v-if="dialog === 'delete'">将删除监控配置并取消未完成任务，已导入照片会保留。</p>
        <template v-else>
          <n-select v-if="dialog === 'resume'" v-model:value="mode" aria-label="恢复方式" :options="[{ value: 'catch_up', label: '补齐暂停期间' }, { value: 'new', label: '不补，只收之后新增' }, { value: 'start', label: '指定起始时间' }]" />
          <template v-if="dialog === 'backfill' || mode === 'start'">
            <label class="field-label">起始时间<LocalDateTime aria-label="起始时间" v-model="since" /></label>
            <DateRangeHint :start="since" end="" />
            <p v-if="dialog === 'backfill'" class="hint">补拉该时刻至提交时刻的帖子，跳过已有媒体。一次性补齐不会修改自动监控进度。</p>
            <p v-else class="hint">将以所选时间作为新的采集起点，重新开始自动增量检查，跳过已有媒体。</p>
            <p v-if="since && !validSince" class="error-text">起始时间必须早于当前时间。</p>
          </template>
        </template>
        <div class="monitor-toolbar">
          <n-button :disabled="busy" @click="dialog = null">取消</n-button>
          <n-button type="primary" :loading="busy" :disabled="busy || ((dialog === 'backfill' || (dialog === 'resume' && mode === 'start')) && !validSince)" @click="confirm">确认{{ dialog === 'delete' ? '删除' : dialog === 'resume' ? '恢复' : '补齐' }}</n-button>
        </div>
      </n-card>
    </n-modal>
  </div>
</template>
<style scoped>
.monitor-manager { display: grid; gap: 24px; }
.monitor-create { display: grid; gap: 12px; max-width: 760px; }
.monitor-create h2 { margin: 0; }
.monitor-fields, .monitor-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.monitor-fields > label { flex: 1 1 180px; min-width: 0; }
.monitor-list { list-style: none; margin: 0; padding: 0; }
.monitor-list li { padding: 20px 0; border-top: 1px solid var(--line); }
.monitor-list .monitor-fields { margin-top: 12px; max-width: 400px; }
.monitor-dialog { width: min(540px, calc(100vw - 32px)); }
.monitor-dialog .monitor-toolbar { margin-top: 24px; justify-content: flex-end; }
</style>
