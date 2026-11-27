<script setup lang="ts">
import OpenGraphSettings from "./OpenGraphSettings.vue";
import MediaCacheStatus from "./MediaCacheStatus.vue";
import LocalDateTime from "./LocalDateTime.vue";
import LoadingOverlay from "./LoadingOverlay.vue";
import ListPagination from "./ListPagination.vue";
import TaskTable, { taskStatusLabels, type TaskRecord } from "./TaskTable.vue";
import { taskKindLabels, taskTypeOptions, tierLabels } from './task-types';
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useLatestRequest } from "./use-latest-request";
import { useRoute } from "vue-router";
import {
  NButton,
  NCheckbox,
  NInput,
  NSelect,
  NTreeSelect,
  NAlert,
  NInputNumber,
  NSlider,
  useMessage,
} from "naive-ui";
import NavigationMenu from './NavigationMenu.vue';
import AdminNavigation, { adminSections } from './AdminNavigation.vue';
import { api, send } from "./api";
import { useLibrary } from "./store";
import { usePageTitle } from "./page-title";
import FeedSourceFields from './FeedSourceFields.vue';
import FeedFormActions from './FeedFormActions.vue';
import { defaultScope, feedPlatforms, importScopePlatforms } from './feed-scope';
import { usePublisherSelection, mergeImportUrls } from "./publisher-selection";
import Monitors from "./Monitors.vue";
import Publishers from './Publishers.vue';
import HashtagField from "./HashtagField.vue";
import People from "./People.vue";
import Review from "./Review.vue";
import DuplicateReview from "./DuplicateReview.vue";
import DateRangeHint from "./DateRangeHint.vue";
import CookieGuide from "./CookieGuide.vue";
const store = useLibrary();
const { selected: publishers, accounts: publisherAccounts } = usePublisherSelection();
const importPlatforms = ref([...feedPlatforms]);
const scope = ref({ ...defaultScope });
const importAccounts = computed(() => publisherAccounts.value.filter(account => importPlatforms.value.includes(account.platform)));
const importUrls = computed(() => mergeImportUrls(importAccounts.value, urls.value));
const targetPlatforms = computed(() => importScopePlatforms(importUrls.value));
const effectiveScope = computed(() => {
  const { retweets, quoted, stories, tagged, reposts } = scope.value;
  return {
    ...(targetPlatforms.value.has('x') ? { retweets, quoted } : {}),
    ...(targetPlatforms.value.has('instagram') ? { stories, tagged, reposts } : {}),
  };
});
const invalidImportRange = computed(() => !effectiveScope.value.reposts && !!start.value && !!end.value && Date.parse(start.value) >= Date.parse(end.value));
const route = useRoute(),
  message = useMessage(),
  authenticated = ref(false),
  checking = ref(true),
  password = ref(""),
  error = ref(""),
  busy = ref(false),
  urls = ref(""),
  hashtags = ref<string[]>([]),
  directory = ref<string | null>(null),
  directories = ref<string[]>([]),
  tasks = ref<TaskRecord[]>([]),
  taskPage = ref(1),
  taskTotal = ref(0),
  tasksLoading = ref(false),
  tasksError = ref(""),
  results = ref<any[]>([]),
  start = ref(""),
  end = ref(""),
  settings = ref<any>(null),
  savingSettings = ref(false);
function updateDuplicateThresholds(values: number[]) {
  const [lower, upper] = [...values].sort((a, b) => a - b);
  settings.value.review_ssim_threshold = lower;
  settings.value.ssim_threshold = upper;
}
const vThresholdLabels = {
  mounted(el: HTMLElement) {
    el.querySelectorAll('[role="slider"]').forEach((handle, index) =>
      handle.setAttribute("aria-label", index === 0 ? "待审核 SSIM 下限" : "自动合并 SSIM 下限"));
  },
};
const section = computed(() => String(route.params.section || "import"));
const taskKinds = ref<string[]>(route.query.kind ? [String(route.query.kind)] : []);
const taskStatuses = ref<string[]>([]);
const taskTiers = ref<string[]>([]);
const taskTierOptions = Object.entries(tierLabels).map(([value, label]) => ({ value, label }));
const hasImported = ref(false);
const taskStatusOptions = Object.entries(taskStatusLabels).map(([value, label]) => ({ value, label }));
const hasTaskFilters = computed(() => taskKinds.value.length || taskStatuses.value.length || taskTiers.value.length || hasImported.value);
function clearTaskFilters() {
  taskKinds.value = [];
  taskStatuses.value = [];
  taskTiers.value = [];
  hasImported.value = false;
}
watch([taskKinds, taskStatuses, taskTiers, hasImported], () => {
  tasksError.value = "";
  void loadTasks(1);
});
const taskPageSize = 20;
const taskPageCount = computed(() =>
  Math.max(1, Math.ceil(taskTotal.value / taskPageSize)),
);
let taskRequest = 0;
let taskPending = false;
const taskRead = useLatestRequest();
let requestedTaskPage = 1;
async function loadTasks(page = taskPage.value, background = false) {
  if (background && taskPending) return;
  const signal = taskRead.start();
  const request = ++taskRequest;
  requestedTaskPage = page;
  taskPending = true;
  tasksLoading.value = !background;
  const query = new URLSearchParams({ page: String(page), page_size: String(taskPageSize) });
  taskKinds.value.forEach(key => query.append(key in taskKindLabels ? 'kind' : 'subtype', key));
  taskTiers.value.forEach(tier => query.append('tier', tier));
  if (hasImported.value) query.set('has_imported', 'true');
  taskStatuses.value.forEach((status) => query.append("status", status));
  try {
    const data = await api<{
      items: (Omit<TaskRecord, 'payload' | 'result'> & { payload: string; result?: string })[];
      total: number;
      page: number;
    }>(`/admin/tasks?${query}`, { signal });
    if (request !== taskRequest) return;
    tasks.value = data.items.map(task => ({ ...task, payload: JSON.parse(task.payload), result: JSON.parse(task.result || "{}") }));
    taskTotal.value = data.total;
    taskPage.value = data.page;
    tasksError.value = "";
  } catch (e) {
    if (request === taskRequest) tasksError.value = (e as Error).message;
  } finally {
    if (request === taskRequest) taskPending = tasksLoading.value = false;
  }
}
const sectionTitle = computed(() => adminSections.find(item => item.id === section.value)?.label || '管理工作台');
usePageTitle(() => {
  if (!checking.value && !authenticated.value) return "管理员登录";
  return sectionTitle.value;
});
async function refresh() {
  if (section.value === "import") {
    await Promise.all([
      api("/admin/directories").then(value => directories.value = value),
      loadTasks(),
      store.load(),
    ]);
  } else if (section.value === "settings") {
    settings.value = await api("/admin/settings");
  } else {
    await store.load();
  }
}
async function login() {
  busy.value = true;
  error.value = "";
  try {
    await send("/login", { password: password.value });
    password.value = "";
    authenticated.value = true;
    await refresh();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function logout() {
  await send("/logout", {});
  authenticated.value = false;
}
function resetImport() {
  if (busy.value) return;
  publishers.value = [];
  importPlatforms.value = [...feedPlatforms];
  scope.value = { ...defaultScope };
  urls.value = "";
  hashtags.value = [];
  directory.value = null;
  start.value = "";
  end.value = "";
  error.value = "";
  results.value = [];
}
async function submitImport() {
  if (busy.value || invalidImportRange.value || (!importUrls.value.length && directory.value === null)) return;
  busy.value = true;
  error.value = "";
  try {
    results.value = await send("/admin/import", {
      urls: importUrls.value,
      hashtags: importUrls.value.length ? hashtags.value : [],
      directory: directory.value,
      scope: effectiveScope.value,
      ...(effectiveScope.value.reposts ? {} : { start: start.value, end: end.value }),
    });
    await loadTasks(1);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
async function taskAction(id: number, action: string) {
  try {
    await send(`/admin/tasks/${id}/${action}`, {});
    await loadTasks();
  } catch (e) {
    message.error((e as Error).message);
  }
}
async function saveSettings() {
  if (savingSettings.value) return;
  savingSettings.value = true;
  try {
    await send("/admin/settings", settings.value, "PUT");
    await store.loadSite(true);
    settings.value.site_title = store.siteTitle;
    message.success("设置已保存");
  } catch (e) {
    message.error((e as Error).message);
  } finally {
    savingSettings.value = false;
  }
}
async function cookie(platform: string, event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    await api("/admin/cookies/" + platform, { method: "POST", body });
    settings.value = await api("/admin/settings");
    message.success("Cookies 已替换");
  } catch (e) {
    message.error((e as Error).message);
  }
}
async function deleteCookie(platform: string) {
  await api("/admin/cookies/" + platform, { method: "DELETE" });
  settings.value = await api("/admin/settings");
}
watch(section, () => {
  taskRequest++;
  taskRead.cancel();
  taskPending = tasksLoading.value = false;
  if (authenticated.value) void refresh().catch(e => error.value = e.message);
});
function onVisibility() {
  if (document.visibilityState === "visible" && authenticated.value &&
      section.value === "import" && !tasksLoading.value) void loadTasks(taskPage.value, true);
}
document.addEventListener("visibilitychange", onVisibility);
let interval: ReturnType<typeof setInterval>;
onMounted(async () => {
  try {
    await api("/session");
    authenticated.value = true;
    await refresh();
  } catch (e) {
    if (authenticated.value) error.value = (e as Error).message;
  } finally {
    checking.value = false;
  }
  interval = setInterval(async () => {
    if (
      authenticated.value &&
      section.value === "import" &&
      !tasksLoading.value &&
      document.visibilityState === "visible"
    )
      await loadTasks(taskPage.value, true);
  }, 3000);
});
onUnmounted(() => {
  clearInterval(interval);
  document.removeEventListener("visibilitychange", onVisibility);
  taskRequest++;
});
</script>
<template>
  <div v-if="checking" class="initial-loading" aria-busy="true"><LoadingOverlay show center label="正在检查登录状态…" /></div>
  <main v-else-if="!authenticated" class="login">
    <h1>管理员登录</h1>
    <p class="muted">登录后可导入照片、整理人物和审核识别结果</p>
    <n-alert v-if="error" type="error">{{ error }}</n-alert>
    <form @submit.prevent="login">
      <label class="field-label"
        >管理员密码<n-input
          v-model:value="password"
          type="password"
          placeholder="输入管理员密码"
          :input-props="{ autocomplete: 'current-password' }" /></label
      ><n-button class="stable-loading-button" attr-type="submit" type="primary" block :loading="busy"
        >登录工作台</n-button
      >
    </form>
    <router-link to="/">返回照片库</router-link>
  </main>
  <main v-else class="admin-shell" :class="{ 'duplicates-shell': section === 'duplicates' }">
    <NavigationMenu v-slot="{ drawer, close }" :title="sectionTitle" menu="管理菜单" drawer-title="管理工作台">
      <AdminNavigation :section="section" :drawer="drawer" @navigate="close" @logout="close(); logout()" />
    </NavigationMenu>
    <section class="admin-content">
      <h1>{{ sectionTitle }}</h1>
      <Monitors v-if="section === 'monitors'" />
      <Publishers v-else-if="section === 'publishers'" />
      <n-alert v-if="error" type="error" closable @close="error = ''">{{
        error
      }}</n-alert><template v-if="section === 'import'"
        ><p class="intro">
          添加帖子或账号链接，或导入已挂载的 gallery-dl 目录
        </p>
        <form class="feed-form import-form" @submit.prevent="submitImport" @reset.prevent="resetImport">
          <FeedSourceFields v-model:publishers="publishers" v-model:platforms="importPlatforms" v-model:scope="scope" :disabled="busy" :target-platforms="targetPlatforms" single-import>
            <p v-if="publishers.length && !importAccounts.length" class="hint" role="status">没有匹配的发布者账号，仍可导入手动链接或目录。</p>
            <label class="field-label">链接，每行一个<n-input v-model:value="urls" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" placeholder="https://www.instagram.com/p/…&#10;https://x.com/username/status/…" /></label>
          </FeedSourceFields>
          <HashtagField v-model="hashtags" :disabled="busy || !importUrls.length" />
          <label class="field-label"
            >或选择导入目录<n-select
              v-model:value="directory"
              clearable
              :options="directories.map((d) => ({ label: d, value: d }))"
              placeholder="挂载目录中的图片与 JSON sidecar"
          /></label>
          <div class="import-dates">
            <div class="inline-form">
              <label class="field-label">开始时间<LocalDateTime aria-label="开始时间" v-model="start" :disabled="busy || effectiveScope.reposts" /></label>
              <label class="field-label">结束时间（不含）<LocalDateTime aria-label="结束时间（不含）" v-model="end" :disabled="busy || effectiveScope.reposts" /></label>
            </div>
            <p v-if="effectiveScope.reposts" class="hint" role="status">包含 Instagram 转发时，不能按日期筛选</p>
            <DateRangeHint v-else :start="start" :end="end" />
            <n-alert v-if="invalidImportRange" type="error">结束时间必须晚于开始时间</n-alert>
          </div>
          <FeedFormActions :busy="busy" :disabled="invalidImportRange || (!importUrls.length && directory === null)">创建导入任务</FeedFormActions>
          <p class="hint">
            再次导入同一账号可获取新增照片，已收录和回收站中的媒体会在下载前跳过
          </p>
        </form>
        <div v-for="(r, i) in results" :key="i" class="import-result">
          <span>{{ r.value }}</span><strong>{{
            r.status === "invalid"
              ? "无效链接"
              : r.status === "duplicate"
                ? "重复链接 / 已在队列"
                : "已加入队列"
          }}</strong>
        </div>
        <div class="task-heading"><h2>任务记录</h2><span>{{ taskTotal }} 条</span>
          <button v-if="hasTaskFilters" type="button" class="text-button" @click="clearTaskFilters">清空筛选</button>
        </div>
        <div class="task-filters">
          <label class="field-label">任务类型
            <n-tree-select v-model:value="taskKinds" role="group" aria-label="任务类型" multiple checkable cascade
              filterable clearable check-strategy="parent" :max-tag-count="1" :options="taskTypeOptions" placeholder="全部类型" />
          </label>
          <label class="field-label">任务状态
            <n-select v-model:value="taskStatuses" role="group" aria-label="任务状态" multiple clearable filterable :max-tag-count="1"
              :input-props="{ 'aria-label': '任务状态' }" placeholder="全部状态" :options="taskStatusOptions" />
          </label>
          <label class="field-label">调度档
            <n-select v-model:value="taskTiers" role="group" aria-label="调度档" multiple clearable filterable :max-tag-count="1"
              :input-props="{ 'aria-label': '调度档' }" placeholder="全部档位" :options="taskTierOptions" />
          </label>
          <n-checkbox v-model:checked="hasImported">有新入库</n-checkbox>
        </div>
        <div class="loading-region" :aria-busy="tasksLoading">
        <LoadingOverlay :show="tasksLoading" label="正在加载任务记录…" />
        <n-alert v-if="tasksError" type="error" title="任务记录加载失败">
          {{ tasksError }}
          <n-button class="stable-loading-button"
            :loading="tasksLoading"
            @click="loadTasks(requestedTaskPage)"
            >重新加载</n-button
          >
        </n-alert>

        <div
          v-if="!tasks.length && !tasksError"
          :style="{ visibility: tasksLoading ? 'hidden' : undefined }"
          class="empty-state"
        >
          <template v-if="hasTaskFilters">
            <h3>没有符合筛选条件的任务</h3>
            <n-button @click="clearTaskFilters">清空筛选</n-button>
          </template>
          <template v-else>
            <h3>还没有导入任务</h3>
            <p>创建任务后，可在这里查看进度、取消或重试</p>
          </template>
        </div>
        <TaskTable v-if="tasks.length" :tasks="tasks" :loading="tasksLoading" @action="taskAction" />
        <nav
          v-if="taskTotal > 0"
          class="task-pagination"
          aria-label="任务记录分页"
        >
          <span class="muted">共 {{ taskTotal }} 条 · 每页 {{ taskPageSize }} 条</span>
          <ListPagination :page="taskPage" :page-count="taskPageCount" :disabled="tasksLoading" @change="loadTasks" />
        </nav></div></template
      ><People v-else-if="section === 'people'" /><Review
        v-else-if="section === 'review'"
      /><DuplicateReview v-else-if="section === 'duplicates'"
      /><template v-else-if="section === 'settings' && settings"
        ><form class="settings-form" @submit.prevent="saveSettings">
          <h2>站点信息</h2>
          <label class="field-label"
            >站点标题<n-input
              v-model:value="settings.site_title"
              :input-props="{ 'aria-label': '站点标题' }"
              placeholder="输入站点标题"
              maxlength="100"
              show-count
              :disabled="savingSettings"
          /></label>
          <p class="hint">显示在页面顶部和浏览器标签页，最多 100 个字符</p>
          <h2>图片审核包</h2>
          <label class="field-label">Agent 审核规则<n-input
            v-model:value="settings.agent_review_rules" type="textarea"
            :input-props="{ 'aria-label': 'Agent 审核规则', 'aria-describedby': 'review-rules-help' }"
            :autosize="{ minRows: 3, maxRows: 12 }" maxlength="4000" show-count :disabled="savingSettings"
          /></label>
          <p id="review-rules-help" class="hint">保存后随新导出的审核包发送。未明确指定回收标准时，agent 不应建议回收图片。</p>
          <h2>链接分享（Open Graph）</h2>
          <p class="hint">分别设置两个前端的分享卡片。标题留空时使用站点标题，其余留空则不提供对应信息。</p>
          <OpenGraphSettings v-model="settings" label="中文前端" suffix="" :disabled="savingSettings" />
          <OpenGraphSettings v-model="settings" label="日语只读前端" suffix="_ja" :disabled="savingSettings" />
          <p class="hint">URL 须以 https:// 或 http:// 开头。预览图须可公开访问；站点 URL 填写对应前端的公开地址。保存后生效，分享平台已有的缓存可能延迟更新。</p>
          <h2>人脸检测</h2>
          <label class="field-label"
            >人脸检测阈值<n-input-number
              :value="settings.detection_threshold == null ? null : Number(settings.detection_threshold)"
              @update:value="settings.detection_threshold = $event"
              :input-props="{ 'aria-label': '人脸检测阈值', 'aria-describedby': 'detection-threshold-help' }"
              :min="0"
              :max="1"
              :step="0.01"
              :disabled="savingSettings"
          /></label>
          <p id="detection-threshold-help" class="hint">
            范围 0–1，默认 0.5。调低可检出更多人脸，也可能增加误检；调高可减少误检，也可能漏检。
            保存后用于后续检测和参考图上传；已有照片需重新检测才会应用
          </p>
          <h2>人物匹配</h2>
          <p class="muted">
            相似度不表示准确率。只有同时满足阈值和领先差值时才会自动采用
          </p>
          <label class="field-label"
            >最低余弦相似度<n-input-number
              :value="Number(settings.threshold)"
              @update:value="settings.threshold = $event"
              :min="0"
              :max="1"
              :step="0.01" /></label
          ><label class="field-label"
            >领先第二人选的差值<n-input-number
              :value="Number(settings.margin)"
              @update:value="settings.margin = $event"
              :min="0"
              :max="2"
              :step="0.01"
          /></label>
          <h2>视觉去重</h2>
          <label class="field-label"
            >pHash 最大距离<n-input-number
              :value="Number(settings.phash_distance)"
              @update:value="settings.phash_distance = $event"
              :min="0"
              :max="64" /></label
          ><label class="field-label"
            >长宽比最大差异<n-input-number
              :value="Number(settings.aspect_tolerance)"
              @update:value="settings.aspect_tolerance = $event"
              :min="0"
              :max="1"
              :step="0.01" /></label
          >
          <div class="field-label">SSIM 阈值</div>
          <div class="hint">待审核下限：{{ Number(settings.review_ssim_threshold ?? 0.5).toFixed(2) }} · 自动合并下限：{{ Number(settings.ssim_threshold).toFixed(2) }}</div>
          <n-slider range :min="0" :max="1" :step="0.01" :disabled="savingSettings"
            :value="[Number(settings.review_ssim_threshold ?? 0.5), Number(settings.ssim_threshold)]"
            @update:value="updateDuplicateThresholds" v-threshold-labels />
          <p class="hint">低于待审核下限的候选不显示，调低后可重新显示。达到自动合并下限还须通过 pHash、长宽比和跨组检查；修改阈值不会撤销已有合并或人工决定。</p>
          <n-button class="stable-loading-button"
            type="primary"
            attr-type="submit"
            :loading="savingSettings"
            :disabled="savingSettings || !settings.site_title?.trim() || settings.detection_threshold == null"
            >保存设置</n-button
          >
        </form>
        <MediaCacheStatus />
        <div class="cookie-heading">
          <h2>平台 Cookies</h2>
          <CookieGuide />
        </div>
        <p class="muted">
          仅接受 Netscape cookies 文件。替换后用于后续下载任务
        </p>
        <div
          v-for="platform in ['x', 'instagram']"
          :key="platform"
          class="cookie-row"
        >
          <h3>{{ platform === "x" ? "X / Twitter" : "Instagram" }}</h3>
          <span>{{
            settings.cookies[platform] ? "已配置" : "未配置"
          }}</span><label class="file-label"
            >上传 / 替换<input
              type="file"
              accept=".txt"
              @change="cookie(platform, $event)" /></label
          ><n-button
            :disabled="!settings.cookies[platform]"
            @click="deleteCookie(platform)"
            >删除</n-button
          >
        </div>
        <h2>识别模型</h2>
        <p>
          {{
            settings.models_ready
              ? "模型文件已安装"
              : "模型尚未安装，请按部署文档安装后再处理图片"
          }}
        </p></template
      >
    </section>
  </main>
</template>

<style scoped>
.import-dates { display: grid; gap: 8px; margin-block: 16px; }
.import-dates :is(.inline-form, .field-label, .hint) { margin: 0; }
.cookie-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 20px;
}
.task-filters {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) repeat(2, minmax(0, 1fr)) auto;
  align-items: flex-end;
  gap: 12px;
}
.task-heading { display: flex; align-items: center; flex-wrap: wrap; min-height: 44px; gap: 8px; margin: 24px 0 12px; }
.task-heading h2 { margin: 0; }
.task-heading > span { color: var(--muted); font-variant-numeric: tabular-nums; }
.task-heading > button { margin-inline-start: auto; }
.task-filters > .n-checkbox { min-height: 44px; align-items: center; justify-self: start; }
.task-filters :deep(.n-base-selection-tags) { flex-wrap: nowrap; }
.task-filters :deep(.n-base-selection) { min-height: 44px; }
.task-filters :deep(.n-tree-select .n-base-selection) { --n-height: 44px !important; }
.task-filters :deep(.n-base-selection-tag-wrapper:first-child), .task-filters :deep(.n-tag__content) { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.task-filters .field-label {
  flex: 1;
  min-width: 0;
  margin: 0;
}
@media (max-width: 640px) {
  .task-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 12px;
  }
}
.task-pagination {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: space-between;
  margin-top: 20px;
  font-variant-numeric: tabular-nums;
}
</style>
