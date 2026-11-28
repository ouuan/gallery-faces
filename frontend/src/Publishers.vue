<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Search } from '@lucide/vue';
import { NAlert, NButton, NCard, NCheckbox, NInput, NModal, NRadioButton, NRadioGroup, NTab, NTabs, useMessage } from 'naive-ui';
import { api, ApiError, platformLabel, send } from './api';
import { scopeLabels } from './feed-scope';
import { accountUrl } from './publisher-selection';
import type { components } from './schema';
import { useLatestRequest } from './use-latest-request';
import ListPagination from './ListPagination.vue';
import PublisherActions from './PublisherActions.vue';
import ListSelectionBar from './ListSelectionBar.vue';

type Publisher = components['schemas']['Publisher'];
type Page = components['schemas']['PublisherPage'];
type Preview = components['schemas']['PurgePreview'];
type Source = Publisher['blocked'][number];
type View = 'posts' | 'rules';
const labels = { ...scopeLabels, all: '全部来源' };
const platform = ref<'x' | 'instagram'>('x');
const view = ref<View>('posts');
const search = ref('');
const pages = ref({ posts: 1, rules: 1 });
const page = computed(() => pages.value[view.value]);
const listing = ref<Page>();
const loading = ref(true);
const listError = ref('');
const moved = ref(false);
const reads = useLatestRequest();
const previewReads = useLatestRequest();
const message = useMessage();
const selected = ref<string[]>([]);
const selectedItems = computed(() => listing.value?.items.filter(item => selected.value.includes(item.username)) ?? []);
const dialog = ref<{ mode: 'rule' | 'purge'; items: Publisher[] } | null>(null);
const keepRules = ref(false);
const showDialog = ref(false);
const preview = ref<Preview>();
const blocked = ref<Source[]>([]);
const dialogError = ref('');
const busy = ref(false);
const indirect = computed<Source[]>(() => platform.value === 'x' ? ['retweets', 'quoted'] : ['tagged', 'reposts']);
const total = computed(() => listing.value?.[view.value === 'posts' ? 'posts_count' : 'rules_count'] ?? 0);
function actionPath(items: Publisher[], action: string) {
  return `/admin/publishers/${platform.value}/${items.length === 1 ? encodeURIComponent(items[0].username) + '/' : 'batch-'}${action}`;
}
const targets = (items: Publisher[]) => items.length === 1 ? {} : { usernames: items.map(item => item.username) };
const profileUrl = (username: string) => accountUrl({ platform: platform.value, username: encodeURIComponent(username) });
const profileLabel = ({ label, username }: Publisher) => label && label !== username ? `${label} @${username}` : `@${username}`;

async function load() {
  const signal = reads.start();
  loading.value = true;
  listError.value = '';
  const query = new URLSearchParams({ platform: platform.value, view: view.value, search: search.value, page: String(page.value) });
  try {
    const result = await api<Page>(`/admin/publishers?${query}`, { signal });
    if (!signal.aborted) {
      listing.value = result;
      pages.value[view.value] = result.page;
    }
  } catch (error) {
    if (!signal.aborted) listError.value = (error as Error).message;
  } finally {
    if (!signal.aborted) loading.value = false;
  }
}
watch([platform, search], () => { pages.value = { posts: 1, rules: 1 }; moved.value = false; });
watch(platform, () => { view.value = 'posts'; });
watch([platform, view, search, page], () => { selected.value = []; void load(); }, { immediate: true });

async function readPreview(items: Publisher[], resetRule: boolean) {
  const signal = previewReads.start();
  const previous = preview.value;
  preview.value = undefined;
  dialogError.value = '';
  try {
    const result = await api<Preview>(actionPath(items, 'purge-preview'), items.length === 1 ? { signal } : { method: 'POST', body: JSON.stringify(targets(items)), signal });
    if (!signal.aborted) {
      preview.value = result;
      if (resetRule || JSON.stringify(previous?.blocked) !== JSON.stringify(result.blocked)) blocked.value = [...result.blocked];
    }
  } catch (error) {
    if (!signal.aborted) dialogError.value = (error as Error).message;
  }
}
function open(mode: 'rule' | 'purge', items: Publisher[]) {
  dialog.value = { mode, items };
  showDialog.value = true;
  blocked.value = items.every(item => JSON.stringify(item.blocked) === JSON.stringify(items[0].blocked)) ? [...items[0].blocked] : [];
  keepRules.value = mode === 'purge' && items.length > 1;
  preview.value = undefined;
  dialogError.value = '';
  if (mode === 'purge') void readPreview(items, true);
}
function close() {
  if (busy.value) return;
  previewReads.cancel();
  showDialog.value = false;
}
function toggle(source: Source, checked: boolean) {
  blocked.value = !checked ? blocked.value.filter(key => key !== source) : source === 'all' ? ['all'] : [...blocked.value.filter(key => key !== 'all'), source];
}
const disabledSource = (source: Source) => busy.value || source !== 'all' && blocked.value.includes('all');
async function submit() {
  if (!dialog.value || busy.value) return;
  const { items, mode } = dialog.value;
  if (mode === 'purge' && (!preview.value || preview.value.references.length)) return;
  busy.value = true;
  dialogError.value = '';
  try {
    if (mode === 'purge') {
      await send(actionPath(items, 'purge'), { ...targets(items), blocked: keepRules.value ? null : blocked.value, scope_token: preview.value!.scope_token });
      moved.value = keepRules.value ? items.some(item => item.blocked.length) : !!blocked.value.length;
      message.success(moved.value ? '帖子已删除，屏蔽规则已保留' : '帖子已彻底删除');
    } else {
      await send(actionPath(items, 'rule'), { ...targets(items), blocked: blocked.value }, 'PUT');
      message.success(blocked.value.length ? '屏蔽规则已保存' : '屏蔽规则已解除');
    }
    showDialog.value = false;
    selected.value = [];
    await load();
  } catch (error) {
    if (mode === 'purge' && error instanceof ApiError && error.status === 409) await readPreview(items, false);
    dialogError.value = (error as Error).message;
  } finally { busy.value = false; }
}
</script>

<template>
  <n-tabs v-model:value="platform" type="line" aria-label="发布者平台" tab-class="publisher-platform-tab"><n-tab name="x">X</n-tab><n-tab name="instagram">Instagram</n-tab></n-tabs>
  <div class="publisher-toolbar">
    <n-input v-model:value="search" clearable placeholder="搜索昵称或用户名" aria-label="搜索昵称或用户名"><template #prefix><Search :size="16" /></template></n-input>
    <n-radio-group v-model:value="view" name="publisher-view" role="radiogroup" aria-label="发布者视图" :theme-overrides="{ buttonHeightMedium: '44px' }">
      <n-radio-button value="posts">有帖子 <small>{{ listing?.posts_count ?? '–' }}</small></n-radio-button>
      <n-radio-button value="rules">仅有屏蔽规则 <small>{{ listing?.rules_count ?? '–' }}</small></n-radio-button>
    </n-radio-group>
  </div>
  <p v-if="moved && view === 'posts'" role="status">帖子已删除，屏蔽规则已保留 <n-button text @click="view = 'rules'; moved = false">查看仅有屏蔽规则的账号</n-button></p>
  <p v-if="view === 'rules'" class="hint">这些账号目前没有帖子，但屏蔽规则仍然生效</p>
  <n-alert v-if="listError" type="error">{{ listError }} <n-button text @click="load">重试</n-button></n-alert>
  <p v-else-if="loading" class="hint" role="status">正在加载发布者…</p>
  <div v-else-if="!listing?.items.length" class="empty-state" role="status">
    <p>{{ search ? '没有匹配的发布者' : view === 'posts' ? '此平台暂无有帖子的未关联发布者' : '此平台暂无仅有屏蔽规则的账号' }}</p>
    <n-button v-if="search && !moved && view === 'posts' && listing?.rules_count" text @click="view = 'rules'">查看仅有屏蔽规则的账号（{{ listing.rules_count }}）</n-button>
  </div>
  <section v-else class="publisher-results" aria-label="发布者列表">
    <ListSelectionBar :count="selected.length" :total="listing.items.length" label="全选本页" @toggle="selected = $event ? listing.items.map(item => item.username) : []">
      <PublisherActions :platform="platform" :usernames="selectedItems.map(item => item.username)" :posts="view === 'posts'" :purge="view === 'posts' && selectedItems.every(item => !item.linked)" @open="open($event, selectedItems)" />
    </ListSelectionBar>
  <ul class="publisher-list">
    <li v-for="item in listing.items" :key="item.username" :class="{ 'is-selected': selected.includes(item.username) }">
      <n-checkbox :aria-label="`选择 ${item.username}`" :checked="selected.includes(item.username)" @update:checked="selected = $event ? [...selected, item.username] : selected.filter(name => name !== item.username)" />
      <div><strong><a :href="profileUrl(item.username)" target="_blank" rel="noopener noreferrer">{{ profileLabel(item) }}</a></strong><span v-if="item.linked" class="hint"> · 已关联</span>
        <p class="hint"><template v-if="item.posts">{{ item.posts }} 个帖子 · </template>{{ item.blocked.length ? '屏蔽：' + item.blocked.map(key => labels[key]).join('、') : '未设置屏蔽' }}</p>
      </div>
      <PublisherActions :platform="platform" :usernames="[item.username]" :posts="!!item.posts" :purge="!!item.posts && !item.linked" @open="open($event, [item])" />
    </li>
  </ul>
  </section>
  <ListPagination v-if="listing && total > listing.page_size" :page="page" :page-count="Math.ceil(total / listing.page_size)" :disabled="loading" @change="pages[view] = $event" />
  <n-modal v-if="dialog" :show="showDialog" :mask-closable="!busy" :close-on-esc="!busy" @update:show="!$event && close()" @after-leave="!showDialog && (dialog = null)">
    <n-card class="publisher-dialog" role="dialog" aria-modal="true" :title="dialog.mode === 'purge' ? '彻底删除帖子' : '设置屏蔽规则'" :aria-label="dialog.mode === 'purge' ? '彻底删除帖子' : '设置屏蔽规则'">
      <strong>{{ platformLabel(platform) }} · <template v-if="dialog.items.length === 1"><a :href="profileUrl(dialog.items[0].username)" target="_blank" rel="noopener noreferrer">{{ profileLabel(dialog.items[0]) }}</a></template><template v-else>{{ dialog.items.length }} 位发布者</template></strong>
      <p v-if="dialog.items.length > 1" class="hint publisher-targets">{{ dialog.items.map(item => '@' + item.username).join('、') }}</p>
      <n-alert v-if="dialogError" type="error">{{ dialogError }} <n-button v-if="dialog.mode === 'purge' && !preview" text @click="readPreview(dialog.items, true)">重新预览</n-button></n-alert>
      <template v-if="dialog.mode === 'purge'">
        <p v-if="preview">将删除 {{ preview.posts }} 个帖子和 {{ preview.exclusive }} 张独占图片（含回收站），保留 {{ preview.shared }} 张共享图片。此操作不可撤销。</p>
        <p v-else-if="!dialogError" role="status">正在核对删除范围…</p>
        <template v-if="preview?.references.length">
          <n-alert type="warning">以下独占图片用作人物参考，无法删除。请先到「人物与分组」移除对应参考，再重新预览。</n-alert>
          <ul class="publisher-references"><li v-for="reference in preview.references" :key="reference.reference_id"><img loading="lazy" :src="`/api/v1/admin/media/${reference.image_id}?thumbnail=true`" alt="" /> 图片 #{{ reference.image_id }} · {{ reference.person }} · 参考 #{{ reference.reference_id }}</li></ul>
          <n-button @click="readPreview(dialog.items, true)">重新预览</n-button>
        </template>
      </template>
      <fieldset v-if="dialog.mode === 'rule' || preview && !preview.references.length" :disabled="busy" class="publisher-rule">
        <legend>{{ dialog.mode === 'purge' ? '删除后的收录规则' : '避免未来收录' }}</legend>
        <p v-if="dialog.mode === 'purge' && dialog.items.length > 1"><n-checkbox v-model:checked="keepRules" :disabled="busy">保留各账号现有规则</n-checkbox></p>
        <template v-if="!keepRules">
          <p v-if="dialog.items.length > 1" class="hint">以下设置将替换所选账号的屏蔽规则</p>
          <n-checkbox v-for="source in (['all', ...indirect] as Source[])" :key="source" :checked="blocked.includes(source)" :disabled="disabledSource(source)" :aria-disabled="disabledSource(source)" @update:checked="toggle(source, $event)">{{ labels[source] }}</n-checkbox>
          <p class="hint">不勾选即不屏蔽。规则适用于监控和手动导入，不影响已有帖子。</p>
        </template>
      </fieldset>
      <template #footer><div class="publisher-actions"><n-button :disabled="busy" @click="close">取消</n-button><n-button :type="dialog.mode === 'purge' ? 'error' : 'primary'" :loading="busy" :disabled="dialog.mode === 'purge' && (!preview || !!preview.references.length)" @click="submit">{{ dialog.mode === 'purge' ? '确认彻底删除' : '保存规则' }}</n-button></div></template>
    </n-card>
  </n-modal>
</template>

<style scoped>
.publisher-toolbar, .publisher-actions, .publisher-references li { display: flex; align-items: center; gap: 12px; }
.publisher-toolbar { flex-wrap: wrap; margin: 16px 0; }
.publisher-toolbar .n-input { flex: 1 1 108px; max-width: 320px; }
.publisher-toolbar .n-radio-group { flex: none; }
.publisher-toolbar small { font-variant-numeric: tabular-nums; }
.publisher-list, .publisher-references { list-style: none; padding: 0; }
.publisher-results { container: publisher-list / inline-size; }
.publisher-list { margin: 16px 0 0; }
.publisher-list li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
.publisher-list li.is-selected { background: color-mix(in srgb, var(--accent) 4%, var(--bg)); }
.publisher-list li > .n-checkbox { min-height: 44px; align-items: center; }
@container publisher-list (max-width: 24rem) {
  .publisher-list li { grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; }
  .publisher-list .publisher-actions { grid-column: 2; justify-self: start; }
}
.publisher-list p { margin: 4px 0 0; }
.publisher-actions { justify-content: flex-end; }
.publisher-actions a:hover { text-decoration: none; }
.publisher-dialog { width: min(520px, calc(100vw - 32px)); max-height: 90dvh; overflow-y: auto; }
.publisher-dialog strong, .publisher-targets { overflow-wrap: anywhere; }
.publisher-dialog .n-alert { margin-top: 12px; }
.publisher-rule { padding: 0; border: 0; margin: 20px 0 0; }
.publisher-rule legend { font-weight: 600; margin-bottom: 8px; }
.publisher-rule .n-checkbox { margin-right: 16px; }
.publisher-references li { margin: 8px 0; }
.publisher-references img { width: 48px; height: 48px; object-fit: contain; }
@media (max-width: 640px) { .publisher-toolbar { gap: 8px; } .publisher-toolbar :deep(.n-radio-button) { padding-inline: 7px; } }
@media (pointer: coarse) { .publisher-rule .n-checkbox { min-height: 44px; display: inline-flex; align-items: center; } }
</style>
