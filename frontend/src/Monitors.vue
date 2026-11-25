<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from "vue";
import { NButton, NInput, NInputNumber, NSelect, NCheckbox, NModal, NCard, NAlert, NTabs, NTab } from "naive-ui";
import { Trash2 } from "@lucide/vue";
import { api, send, dateLabel, platformLabel } from "./api";
import FeedSourceFields from './FeedSourceFields.vue';
import FeedFormActions from './FeedFormActions.vue';
import FeedScopeFields from './FeedScopeFields.vue';
import { defaultScope, feedPlatforms, monitorScope, supportsAccountScope } from './feed-scope';
import { usePublisherSelection, uniqueAccounts, type PublisherAccount } from "./publisher-selection";
import LocalDateTime from "./LocalDateTime.vue";
import MonitorMoreActions from './MonitorMoreActions.vue';
import HashtagField, { formatHashtags } from "./HashtagField.vue";
import type { components } from "./schema";
type Monitor = components["schemas"]["Monitor"];
const items = ref<Monitor[]>([]), selected = ref<number[]>([]), error = ref(""), busy = ref(false), loading = ref(false);
const activePlatform = ref('x');
const visibleMonitors = computed(() => items.value.filter(item => item.platform === activePlatform.value));
const createExpanded = ref(false), loaded = ref(false);
const createForm = ref<HTMLFormElement | null>(null);
const createToggle = ref<InstanceType<typeof NButton> | null>(null);
let createToggled = false;
async function toggleCreate() {
  if (busy.value) return;
  createToggled = true;
  createExpanded.value = !createExpanded.value;
  await nextTick();
  if (createExpanded.value) createForm.value?.querySelector<HTMLElement>('.publisher-cascader [tabindex="0"], .publisher-cascader input')?.focus();
  else createToggle.value?.$el.focus();
}
const batchInterval = ref<number | null>(60);
const validInterval = computed(() => batchInterval.value !== null && Number.isInteger(batchInterval.value) && batchInterval.value >= 5);
const { selected: publishers, accounts: publisherAccounts } = usePublisherSelection();
const platforms = ref([...feedPlatforms]);
const scope = ref({ ...defaultScope }), editScope = ref({ ...defaultScope }), editPlatform = ref('x');
const listUrls = ref("");
const manualAccounts = ref<PublisherAccount[]>([{ platform: "x", username: "" }]);
const interval = ref(60), start = ref(""), history = ref(false);
const hashtags = ref<string[]>([]), editHashtags = ref<string[]>([]);
const accounts = computed(() => uniqueAccounts([...publisherAccounts.value.filter(account => platforms.value.includes(account.platform)), ...manualAccounts.value, ...listUrls.value.split("\n").map(username => ({ platform: "x", username: normalizeList(username) }))]));
function normalizeList(value: string) {
  try {
    const url = new URL(value.trim());
    if (url.protocol === "https:" && /^(www\.)?(x|twitter)\.com$/.test(url.hostname) && !url.username && !url.password && !url.port && /^\/i\/lists\/[0-9]+\/?$/.test(url.pathname)) return url.pathname.replace(/^\/|\/$/g, "");
  } catch { /* Keep invalid input so the API can report it. */ }
  return value.trim();
}
const invalidList = computed(() => listUrls.value.split("\n").some(value => value.trim() && !/^i\/lists\/[0-9]+$/.test(normalizeList(value))));
function monitorUrl(account: PublisherAccount) {
  const path = account.username.split("/").map(encodeURIComponent).join("/");
  return `https://${account.platform === "x" ? "x.com" : "www.instagram.com"}/${path}/`;
}
function monitorLabel(account: PublisherAccount, nickname?: string | null) {
  return account.platform === "x" && account.username.startsWith("i/lists/")
    ? `Twitter List ${account.username.slice(8)}`
    : `${nickname && nickname.toLowerCase() !== account.username.toLowerCase() ? nickname + ' ' : ''}@${account.username}`;
}
const createResults = ref<{ account: PublisherAccount; error?: string }[]>([]);
const completedAccounts = ref<PublisherAccount[]>([]), batchDefaultStart = ref("");
const pendingAccounts = computed(() => accounts.value.filter(account => !completedAccounts.value.some(done => done.platform === account.platform && done.username === account.username)));
const targetPlatforms = computed(() => new Set(pendingAccounts.value.filter(account => supportsAccountScope(account.platform, account.username)).map(account => account.platform)));
type Dialog = "delete" | "backfill" | "resume" | "interval" | "hashtags" | "scope";
const dialog = ref<Dialog | null>(null), targets = ref<number[]>([]), since = ref(""), mode = ref("catch_up");
const results = ref<components['schemas']['BatchResult'][]>([]);
const selectedMonitors = computed(() => {
  const ids = new Set(selected.value);
  return visibleMonitors.value.filter(item => ids.has(item.id));
});
const pausable = computed(() => selectedMonitors.value.filter(item => !item.paused).map(item => item.id));
const resumable = computed(() => selectedMonitors.value.filter(item => item.paused && !item.active_task_id).map(item => item.id));
const all = computed(() => visibleMonitors.value.length > 0 && selected.value.length === visibleMonitors.value.length);
function switchPlatform(platform: string) {
  if (busy.value || platform === activePlatform.value) return;
  activePlatform.value = platform;
  selected.value = [];
  results.value = [];
}
function focusPlatform(platform: string) {
  switchPlatform(platform);
  document.getElementById(`monitor-tab-${activePlatform.value}`)?.focus();
}
const updatedLabel = ref('');
const dialogTitle = computed(() => dialog.value === 'scope' ? '修改抓取范围' : dialog.value === "hashtags" ? "修改话题标签" : dialog.value === "interval" ? "修改 " + targets.value.length + " 项监控的间隔" : dialog.value === "delete" ? "删除 " + targets.value.length + " 项监控" : dialog.value === "resume" ? "恢复监控" : "补齐 " + targets.value.length + " 位发布者");
const validSince = computed(() => !!since.value && Date.parse(since.value) < Date.now());
let timer: ReturnType<typeof setInterval> | undefined;
async function load() {
  loading.value = true;
  try {
    items.value = await api<Monitor[]>("/admin/monitors");
    if (!loaded.value && !createToggled) createExpanded.value = items.value.length === 0;
    loaded.value = true;
    selected.value = selected.value.filter(id => visibleMonitors.value.some(item => item.id === id));
  } catch (e) { error.value = (e as Error).message; }
  finally { loading.value = false; }
}
async function perform(action: () => Promise<unknown>) {
  busy.value = true; error.value = "";
  try { await action(); await load(); }
  catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}
function clearCreateBatch() {
  publishers.value = [];
  manualAccounts.value = [{ platform: "x", username: "" }];
  listUrls.value = "";
  hashtags.value = [];
  start.value = "";
  history.value = false;
  completedAccounts.value = [];
  batchDefaultStart.value = "";
}
function resetCreate() {
  if (busy.value) return;
  clearCreateBatch();
  platforms.value = [...feedPlatforms];
  scope.value = { ...defaultScope };
  interval.value = 60;
  createResults.value = [];
}
async function create() {
  if (busy.value || invalidList.value || !pendingAccounts.value.length || !interval.value || (history.value && !start.value)) return;
  const batchAccounts = [...pendingAccounts.value];
  batchDefaultStart.value ||= new Date().toISOString();
  const batchStart = history.value ? start.value : batchDefaultStart.value;
  const batchInterval = interval.value;
  const batchHashtags = hashtags.value;
  await perform(async () => {
    createResults.value = completedAccounts.value.map(account => ({ account }));
    for (const account of batchAccounts) {
      try {
        await send("/admin/monitors", { ...account, interval_minutes: batchInterval, start: batchStart, hashtags: batchHashtags, scope: monitorScope(account.platform, scope.value) });
        createResults.value.push({ account });
        completedAccounts.value.push(account);
      } catch (e) { createResults.value.push({ account, error: (e as Error).message }); }
    }
    if (createResults.value.every(result => !result.error)) clearCreateBatch();
  });
}
function open(action: Dialog, ids: number[]) {
  const item = items.value.find(item => item.id === ids[0]);
  batchInterval.value = item?.interval_minutes ?? 60;
  editHashtags.value = [...(item?.hashtags ?? [])];
  editPlatform.value = item?.platform ?? 'x';
  editScope.value = { ...defaultScope, ...item?.scope };
  error.value = ""; targets.value = [...ids]; since.value = ""; mode.value = "catch_up"; dialog.value = action;
}
async function batch(action: components['schemas']['Batch']['action'], ids: number[]) {
  if (busy.value || !ids.length || (action === "interval" && !validInterval.value)) return;
  const intervalMinutes = batchInterval.value;
  await perform(async () => {
    results.value = await send("/admin/monitors/batch", { action, ids: [...ids], start: since.value, ...(action === 'resume' ? { mode: mode.value } : {}), ...(action === "interval" ? { interval_minutes: intervalMinutes } : {}), ...(action === 'scope' ? { scope: monitorScope(editPlatform.value, editScope.value) } : {}) });
    updatedLabel.value = action === 'scope' ? '已修改抓取范围' : '已修改检查间隔';
    dialog.value = null;
  });
}
async function confirm() {
  if (dialog.value === 'scope' && targets.value.length === 1) {
    await perform(async () => {
      await send('/admin/monitors/' + targets.value[0], { scope: monitorScope(editPlatform.value, editScope.value) }, 'PATCH');
      dialog.value = null;
    });
  } else if (dialog.value === "hashtags") {
    await perform(async () => {
      await send("/admin/monitors/" + targets.value[0], { hashtags: editHashtags.value }, "PATCH");
      dialog.value = null;
    });
  } else if (dialog.value) await batch(dialog.value, targets.value);
}
function toggle(ids: number[], checked: boolean) {
  const next = new Set(selected.value);
  for (const id of ids) {
    if (checked) next.add(id);
    else next.delete(id);
  }
  selected.value = [...next];
}
function resultLabel(item: Monitor) {
  const result = JSON.parse(item.last_result || "{}");
  const status = item.last_status && (({ done: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[item.last_status] || item.last_status);
  const counts = 'imported' in result ? `新入库 ${result.imported} · 跳过已收录 ${result.skipped_existing} · 跳过回收站 ${result.skipped_trashed}` : '';
  return [status, counts].filter(Boolean).join(' · ') || (item.last_checked_at ? '暂无导入结果' : '');
}
const monitorRows = computed(() => visibleMonitors.value.map(item => ({ ...item, label: monitorLabel(item, item.nickname), outcome: resultLabel(item) })));
function batchResultLabel(result: components['schemas']['BatchResult']) {
  switch (result.status) {
    case 'error': return result.error || '操作失败';
    case 'updated': return updatedLabel.value;
    case 'deleted': return '已删除监控，已导入照片保留';
    case 'paused': return '已暂停';
    case 'resumed': return `已继续监控 · 任务 #${result.task_id}`;
    case 'queued': return `任务 #${result.task_id} 已提交或复用`;
  }
}
onMounted(() => { void load(); timer = setInterval(() => { if (!busy.value && !loading.value) void load(); }, 5000); });
onUnmounted(() => { clearInterval(timer); });
</script>
<template>
  <div class="monitor-manager">
    <n-alert v-if="error" type="error">{{ error }}</n-alert>
    <div class="monitor-header">
      <span class="muted">{{ loaded ? `共 ${items.length} 项监控` : '正在加载监控…' }}</span>
      <div class="monitor-toolbar">
        <n-button ref="createToggle" :type="createExpanded ? 'default' : 'primary'" :disabled="busy" :aria-expanded="createExpanded" aria-controls="monitor-create" @click="toggleCreate">{{ createExpanded ? '收起添加' : '添加发布者' }}</n-button>
        <n-button :loading="loading" @click="load">刷新</n-button>
        <router-link to="/admin/import?kind=monitor">查看监控任务</router-link>
      </div>
    </div>
    <form v-show="createExpanded" id="monitor-create" ref="createForm" class="feed-form monitor-create" @submit.prevent="create" @reset.prevent="resetCreate">
      <h2>添加发布者</h2>
      <FeedSourceFields v-model:publishers="publishers" v-model:platforms="platforms" v-model:scope="scope" :disabled="busy" :target-platforms="targetPlatforms">
        <p class="hint">平台选择统一应用于所有所选人物，默认添加全部平台；手动账号和 List 单独添加</p>
        <p v-if="publishers.length && !publisherAccounts.some(account => platforms.includes(account.platform))" class="hint" role="status">所选人物在这些平台没有关联账号，请调整平台或人物选择</p>
        <div class="section-heading"><h3>手动账号</h3><n-button :disabled="busy" @click="manualAccounts.push({ platform: 'x', username: '' })">添加账号</n-button></div>
        <div v-for="(account, i) in manualAccounts" :key="i" class="monitor-manual-account">
          <label class="field-label">平台<n-select v-model:value="account.platform" :aria-label="`账号 ${i + 1} 平台`" :disabled="busy" :options="[{ label: 'X', value: 'x' }, { label: 'Instagram', value: 'instagram' }]" /></label>
          <label class="field-label">用户名<n-input v-model:value="account.username" :aria-label="`账号 ${i + 1} 用户名`" :disabled="busy" placeholder="用户名，不含 @" /></label>
          <n-button quaternary :disabled="busy" :aria-label="`移除账号 ${i + 1}`" title="移除账号" @click="manualAccounts.splice(i, 1)"><template #icon><Trash2 /></template></n-button>
        </div>
        <label class="field-label">Twitter List
          <n-input v-model:value="listUrls" :status="invalidList ? 'error' : undefined" aria-label="Twitter List 链接" type="textarea" :disabled="busy" :autosize="{ minRows: 2, maxRows: 5 }" placeholder="https://x.com/i/lists/123456789，每行一个链接" />
        </label>
        <p v-if="invalidList" class="error-text" role="alert">请输入有效的 x.com/i/lists/数字 或 twitter.com/i/lists/数字 HTTPS 链接，每行一个</p>
      </FeedSourceFields>
      <HashtagField v-model="hashtags" :disabled="busy" />
      <label class="field-label">检查间隔（分钟）<n-input-number v-model:value="interval" :disabled="busy" :min="5" :precision="0" /></label>
      <div class="monitor-history">
        <n-checkbox v-model:checked="history" :disabled="busy">指定起始时间，补拉历史</n-checkbox>
        <label v-if="history" class="field-label">起始时间<LocalDateTime aria-label="起始时间" v-model="start" :disabled="busy" /></label>
        <p v-else class="hint">默认只收新增，以保存时刻为起点。</p>
      </div>
      <FeedFormActions :busy="busy" :disabled="invalidList || !pendingAccounts.length || !interval || (history && !start)">添加监控</FeedFormActions>
      <p v-if="accounts.length" class="hint">共 {{ accounts.length }} 项监控，统一使用以上间隔和起始时间</p>
      <div v-if="createResults.length" class="monitor-create-results" role="status">
        <p v-for="result in createResults" :key="result.account.platform + ':' + result.account.username" :class="{ 'error-text': result.error }">{{ platformLabel(result.account.platform) }} {{ monitorLabel(result.account) }}：{{ result.error || '已添加监控' }}</p>
      </div>
    </form>
    <n-tabs type="line" role="tablist" aria-label="监控平台" tab-class="publisher-platform-tab" :value="activePlatform" @update:value="switchPlatform">
      <n-tab v-for="platform in feedPlatforms" :key="platform" :name="platform" :id="`monitor-tab-${platform}`" role="tab" :disabled="busy" :aria-selected="activePlatform === platform" aria-controls="monitor-panel" :tabindex="activePlatform === platform ? 0 : -1"
        @keydown.left.prevent="focusPlatform(platform === 'x' ? 'instagram' : 'x')" @keydown.right.prevent="focusPlatform(platform === 'x' ? 'instagram' : 'x')" @keydown.home.prevent="focusPlatform('x')" @keydown.end.prevent="focusPlatform('instagram')">{{ platformLabel(platform) }}</n-tab>
    </n-tabs>
    <section id="monitor-panel" class="monitor-panel" role="tabpanel" :aria-labelledby="`monitor-tab-${activePlatform}`">
    <div v-if="visibleMonitors.length" class="monitor-selection">
      <div class="monitor-selection-summary">
        <n-checkbox :checked="all" :indeterminate="selected.length > 0 && !all" @update:checked="selected = $event ? visibleMonitors.map(item => item.id) : []">全选</n-checkbox>
        <span v-if="selected.length" class="monitor-selection-count">已选 {{ selected.length }} 项</span>
      </div>
      <div v-if="selected.length" class="monitor-actions" role="group" aria-label="批量操作">
        <n-button v-if="pausable.length" :disabled="busy" @click="batch('pause', pausable)">暂停</n-button>
        <n-button v-else :disabled="busy || !resumable.length" @click="open('resume', resumable)">继续</n-button>
        <n-button :disabled="busy" @click="batch('update', selected)">立刻更新</n-button>
        <MonitorMoreActions batch :disabled="busy" @select="open($event, selected)" />
      </div>
    </div>
    <div v-if="results.length" role="status">
      <p v-for="result in results" :key="result.id" :class="{ 'error-text': result.error }">
        #{{ result.id }}：{{ batchResultLabel(result) }}
      </p>
    </div>
    <p v-if="loaded && !visibleMonitors.length" class="hint">还没有 {{ platformLabel(activePlatform) }} 发布者监控。</p>
    <ul class="monitor-list" :aria-busy="loading">
      <li v-for="item in monitorRows" :key="item.id" :class="{ 'is-selected': selected.includes(item.id) }">
        <n-checkbox :aria-label="'选择 ' + item.username" :checked="selected.includes(item.id)" @update:checked="toggle([item.id], $event)" />
        <div class="monitor-summary">
          <strong><a :href="monitorUrl(item)" target="_blank" rel="noopener noreferrer">{{ item.label }}</a></strong>
          <p class="hint">{{ item.paused ? (item.active_task_id ? '已暂停，等待任务结束' : '已暂停') : item.active_task_id ? '检查中' : '监控中' }} · 检查间隔 {{ item.interval_minutes }} 分钟</p>
          <p v-if="item.hashtags?.length" class="hint">{{ formatHashtags(item.hashtags) }}</p>
        </div>
        <dl class="monitor-schedule">
          <dt>下次检查</dt><dd>{{ item.paused ? '已暂停' : dateLabel(item.next_check_at) }}</dd>
          <dt>上次检查</dt><dd>{{ item.last_checked_at ? dateLabel(item.last_checked_at) : '尚未检查' }}</dd>
        </dl>
        <div v-if="item.outcome || item.last_error" class="monitor-outcome">
          <p v-if="item.outcome" class="hint">{{ item.outcome }}</p>
          <p v-if="item.last_error" class="error-text">{{ item.last_error }}</p>
        </div>
        <div class="monitor-actions" role="group" :aria-label="item.label + ' 操作'">
          <n-button v-if="!item.paused" :disabled="busy" @click="batch('pause', [item.id])">暂停</n-button>
          <n-button v-else :disabled="busy || !!item.active_task_id" @click="open('resume', [item.id])">继续</n-button>
          <n-button :disabled="busy" @click="batch('update', [item.id])">立刻更新</n-button>
          <MonitorMoreActions :disabled="busy" @select="open($event, [item.id])" />
        </div>
      </li>
    </ul>
    </section>
    <n-modal :show="!!dialog" :mask-closable="!busy" @update:show="!busy && !$event && (dialog = null)">
      <n-card class="monitor-dialog" role="dialog" aria-modal="true" :title="dialogTitle" :aria-label="dialogTitle">
        <n-alert v-if="error" type="error">{{ error }}</n-alert>
        <p v-if="dialog === 'delete'">将删除监控配置并取消未完成任务，已导入照片会保留。</p>
        <template v-else-if="dialog === 'scope'">
          <p v-if="targets.length > 1">以下范围将覆盖所选 {{ targets.length }} 项 {{ platformLabel(editPlatform) }} 监控的设置，仅对新建任务生效。</p>
          <FeedScopeFields v-model="editScope" :platform="editPlatform" :disabled="busy" />
        </template>
        <template v-else-if="dialog === 'hashtags'">
          <HashtagField v-model="editHashtags" :disabled="busy" />
          <p class="hint">仅影响新建任务。要按新标签检查历史帖子，请使用「补齐」。</p>
        </template>
        <label v-else-if="dialog === 'interval'" class="field-label">检查间隔（分钟）
          <n-input-number v-model:value="batchInterval" aria-label="检查间隔（分钟）" :disabled="busy" :min="5" :precision="0" />
          <span class="hint">统一应用于所选 {{ targets.length }} 项监控，最少 5 分钟</span>
        </label>
        <template v-else>
          <p v-if="dialog === 'resume'">将按以下方式继续 {{ targets.length }} 项监控。</p>
          <n-select v-if="dialog === 'resume'" :to="false" v-model:value="mode" aria-label="恢复方式" :options="[{ value: 'catch_up', label: '补齐暂停期间' }, { value: 'new', label: '不补，只收之后新增' }, { value: 'start', label: '指定起始时间' }]" />
          <template v-if="dialog === 'backfill' || mode === 'start'">
            <label class="field-label">起始时间<LocalDateTime contained aria-label="起始时间" v-model="since" :disabled="busy" /></label>
            <p v-if="dialog === 'backfill'" class="hint">补拉该时刻至提交时刻的帖子，跳过已有媒体。一次性补齐不会修改自动监控进度。</p>
            <p v-else class="hint">将以所选时间作为新的采集起点，重新开始自动增量检查，跳过已有媒体。</p>
            <p v-if="since && !validSince" class="error-text">起始时间必须早于当前时间。</p>
          </template>
        </template>
        <div class="monitor-toolbar">
          <n-button :disabled="busy" @click="dialog = null">取消</n-button>
          <n-button :type="dialog === 'delete' ? 'error' : 'primary'" :loading="busy" :disabled="busy || (dialog === 'interval' && !validInterval) || ((dialog === 'backfill' || (dialog === 'resume' && mode === 'start')) && !validSince)" @click="confirm">确认{{ dialog === 'interval' || dialog === 'hashtags' || dialog === 'scope' ? '修改' : dialog === 'delete' ? '删除' : dialog === 'resume' ? '恢复' : '补齐' }}</n-button>
        </div>
      </n-card>
    </n-modal>
  </div>
</template>
<style scoped>
.monitor-manager { container: monitors / inline-size; display: grid; gap: 24px; min-width: 0; overflow-wrap: anywhere; }
.monitor-list :where(p, dl, dd), .monitor-manager > .hint { margin: 0; }
.monitor-manager :where(.field-label, .monitor-summary) { min-width: 0; }
.monitor-header, .monitor-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.monitor-header { justify-content: space-between; }
.monitor-header a { display: inline-flex; align-items: center; min-height: 44px; }
.monitor-create h2 { font-size: 19px; margin-block: 16px; }
.monitor-create .section-heading { margin: 16px 0 8px; }
.monitor-history { margin-bottom: 16px; }
.monitor-manual-account { display: grid; grid-template-columns: 144px minmax(0, 1fr) auto; align-items: end; gap: 12px; }
.monitor-manual-account .field-label { margin: 0; }
.monitor-manual-account + .monitor-manual-account { margin-top: 8px; }
.monitor-create-results { display: grid; gap: 8px; margin-top: 16px; }
.monitor-list { list-style: none; margin: 0; padding: 0; min-width: 0; }
.monitor-list li { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: start; gap: 12px; padding: 16px 12px; border-top: 1px solid var(--line); }
.monitor-list li.is-selected { background: color-mix(in srgb, var(--accent) 4%, var(--bg)); }
.monitor-list li > .n-checkbox { grid-column: 1; grid-row: 1; min-height: 44px; align-items: flex-start; padding-block-start: 4px; }
.monitor-list li > :not(.n-checkbox) { grid-column: 2; }
.monitor-summary, .monitor-outcome { display: grid; align-content: start; gap: 4px; }
.monitor-summary strong { font-size: 1.067rem; }
.monitor-summary a { word-break: break-all; }
.monitor-schedule { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 12px; align-content: start; font-size: .933rem; font-variant-numeric: tabular-nums; }
.monitor-schedule dt { color: var(--muted); }
.monitor-selection { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 4px 12px; padding: 4px 12px; }
.monitor-selection-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.monitor-selection-summary .n-checkbox { min-height: 44px; align-items: center; }
.monitor-selection-count { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.monitor-selection .monitor-actions { column-gap: 4px; }
.monitor-panel { display: grid; gap: 16px; min-width: 0; }
.monitor-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.monitor-dialog { width: min(540px, calc(100vw - 32px)); max-height: 90dvh; overflow: auto; overflow-wrap: anywhere; }
.monitor-dialog .monitor-toolbar { margin-top: 24px; justify-content: flex-end; }
@container monitors (min-width: 40rem) {
  .monitor-list li { grid-template-columns: auto minmax(0, 1fr) auto; }
  .monitor-list li > .monitor-actions { grid-column: 3; grid-row: 1; }
  .monitor-list li > .monitor-outcome { grid-column: 2 / -1; }
}
@container monitors (min-width: 52rem) {
  .monitor-list li { grid-template-columns: auto minmax(0, 1fr) minmax(16rem, .75fr) auto; }
  .monitor-list li > .monitor-schedule { grid-column: 3; grid-row: 1; }
  .monitor-list li > .monitor-actions { grid-column: 4; }
}
@container monitors (max-width: 479px) {
  .monitor-header { align-items: flex-start; }
  .monitor-manual-account { grid-template-columns: minmax(0, 6.5rem) minmax(0, 1fr) auto; gap: 8px; }
}
</style>
