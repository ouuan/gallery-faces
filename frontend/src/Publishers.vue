<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Search } from '@lucide/vue';
import { NAlert, NButton, NCard, NCheckbox, NDropdown, NInput, NModal, NRadioButton, NRadioGroup, NTab, NTabs, useMessage } from 'naive-ui';
import { api, ApiError, platformLabel, send } from './api';
import { scopeLabels } from './feed-scope';
import { accountUrl } from './publisher-selection';
import type { components } from './schema';
import { useLatestRequest } from './use-latest-request';
import ListPagination from './ListPagination.vue';
import MoreMenuButton from './MoreMenuButton.vue';

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
const dialog = ref<{ mode: 'rule' | 'purge'; item: Publisher } | null>(null);
const showDialog = ref(false);
const preview = ref<Preview>();
const blocked = ref<Source[]>([]);
const dialogError = ref('');
const busy = ref(false);
const indirect = computed<Source[]>(() => platform.value === 'x' ? ['retweets', 'quoted'] : ['tagged', 'reposts']);
const total = computed(() => listing.value?.[view.value === 'posts' ? 'posts_count' : 'rules_count'] ?? 0);
const base = (item: Publisher) => `/admin/publishers/${platform.value}/${encodeURIComponent(item.username)}`;
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
watch([platform, view, search, page], load, { immediate: true });

async function readPreview(item: Publisher, resetRule: boolean) {
  const signal = previewReads.start();
  const previous = preview.value;
  preview.value = undefined;
  dialogError.value = '';
  try {
    const result = await api<Preview>(`${base(item)}/purge-preview`, { signal });
    if (!signal.aborted) {
      preview.value = result;
      if (resetRule || JSON.stringify(previous?.blocked) !== JSON.stringify(result.blocked)) blocked.value = [...result.blocked];
    }
  } catch (error) {
    if (!signal.aborted) dialogError.value = (error as Error).message;
  }
}
function open(mode: 'rule' | 'purge', item: Publisher) {
  dialog.value = { mode, item };
  showDialog.value = true;
  blocked.value = [...item.blocked];
  preview.value = undefined;
  dialogError.value = '';
  if (mode === 'purge') void readPreview(item, true);
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
  const { item, mode } = dialog.value;
  if (mode === 'purge' && (!preview.value || preview.value.references.length)) return;
  busy.value = true;
  dialogError.value = '';
  try {
    if (mode === 'purge') {
      await send(`${base(item)}/purge`, { blocked: blocked.value, scope_token: preview.value!.scope_token });
      moved.value = !!blocked.value.length;
      message.success(moved.value ? '帖子已删除，屏蔽规则已保留' : '帖子已彻底删除');
    } else {
      await send(`${base(item)}/rule`, { blocked: blocked.value }, 'PUT');
      message.success(blocked.value.length ? '屏蔽规则已保存' : '屏蔽规则已解除');
    }
    showDialog.value = false;
    await load();
  } catch (error) {
    if (mode === 'purge' && error instanceof ApiError && error.status === 409) await readPreview(item, false);
    dialogError.value = (error as Error).message;
  } finally { busy.value = false; }
}
const moreActions = [
  { label: '设置屏蔽', key: 'rule', props: { role: 'menuitem' } },
  { label: '彻底删除帖子', key: 'purge', props: { role: 'menuitem', style: { color: 'var(--error)' } } },
];
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
  <p v-if="moved && view === 'posts'" role="status">帖子已删除，屏蔽规则已保留。<n-button text @click="view = 'rules'; moved = false">查看仅有屏蔽规则的账号</n-button></p>
  <p v-if="view === 'rules'" class="hint">这些账号目前没有帖子，但屏蔽规则仍然生效。</p>
  <n-alert v-if="listError" type="error">{{ listError }} <n-button text @click="load">重试</n-button></n-alert>
  <p v-else-if="loading" class="hint" role="status">正在加载发布者…</p>
  <div v-else-if="!listing?.items.length" class="empty-state" role="status">
    <p>{{ search ? '没有匹配的发布者' : view === 'posts' ? '此平台暂无有帖子的未关联发布者' : '此平台暂无仅有屏蔽规则的账号' }}</p>
    <n-button v-if="search && !moved && view === 'posts' && listing?.rules_count" text @click="view = 'rules'">查看仅有屏蔽规则的账号（{{ listing.rules_count }}）</n-button>
  </div>
  <ul v-else class="publisher-list">
    <li v-for="item in listing.items" :key="item.username">
      <div><strong><a :href="profileUrl(item.username)" target="_blank" rel="noopener noreferrer">{{ profileLabel(item) }}</a></strong><span v-if="item.linked" class="hint"> · 已关联</span>
        <p class="hint"><template v-if="item.posts">{{ item.posts }} 个帖子 · </template>{{ item.blocked.length ? '屏蔽：' + item.blocked.map(key => labels[key]).join('、') : '未设置屏蔽' }}</p>
      </div>
      <div class="publisher-actions" v-if="item.posts">
        <router-link custom v-slot="{ href, navigate }" :to="{ path: '/admin/review', query: { state: 'all', publishers: `${platform}:${item.username}` } }">
          <n-button tag="a" :href="href" @click="navigate">查看审核</n-button>
        </router-link>
        <n-button :class="{ 'publisher-direct': !item.linked }" @click="open('rule', item)">设置屏蔽</n-button>
        <template v-if="!item.linked">
          <n-button class="publisher-direct" ghost type="error" :theme-overrides="{ borderError: '1px solid var(--line)' }" @click="open('purge', item)">彻底删除帖子</n-button>
          <n-dropdown trigger="click" placement="bottom-end" :options="moreActions" :menu-props="() => ({ role: 'menu' })" @select="key => open(key, item)">
            <MoreMenuButton class="publisher-more" :label="`更多操作 @${item.username}`" />
          </n-dropdown>
        </template>
      </div>
      <n-button v-else @click="open('rule', item)">编辑规则</n-button>
    </li>
  </ul>
  <ListPagination v-if="listing && total > listing.page_size" :page="page" :page-count="Math.ceil(total / listing.page_size)" :disabled="loading" @change="pages[view] = $event" />
  <n-modal v-if="dialog" :show="showDialog" :mask-closable="!busy" :close-on-esc="!busy" @update:show="!$event && close()" @after-leave="!showDialog && (dialog = null)">
    <n-card class="publisher-dialog" role="dialog" aria-modal="true" :title="dialog.mode === 'purge' ? '彻底删除帖子' : '设置屏蔽规则'" :aria-label="dialog.mode === 'purge' ? '彻底删除帖子' : '设置屏蔽规则'">
      <strong>{{ platformLabel(platform) }} · <a :href="profileUrl(dialog.item.username)" target="_blank" rel="noopener noreferrer">{{ profileLabel(dialog.item) }}</a></strong>
      <n-alert v-if="dialogError" type="error">{{ dialogError }} <n-button v-if="dialog.mode === 'purge' && !preview" text @click="readPreview(dialog.item, true)">重新预览</n-button></n-alert>
      <template v-if="dialog.mode === 'purge'">
        <p v-if="preview">将删除 {{ preview.posts }} 个帖子和 {{ preview.exclusive }} 张独占图片（含回收站），保留 {{ preview.shared }} 张共享图片。此操作不可撤销。</p>
        <p v-else-if="!dialogError" role="status">正在核对删除范围…</p>
        <template v-if="preview?.references.length">
          <n-alert type="warning">以下独占图片用作人物参考，无法删除。请先到「人物与分组」移除对应参考，再重新预览。</n-alert>
          <ul class="publisher-references"><li v-for="reference in preview.references" :key="reference.reference_id"><img loading="lazy" :src="`/api/v1/admin/media/${reference.image_id}?thumbnail=true`" alt="" /> 图片 #{{ reference.image_id }} · {{ reference.person }} · 参考 #{{ reference.reference_id }}</li></ul>
          <n-button @click="readPreview(dialog.item, true)">重新预览</n-button>
        </template>
      </template>
      <fieldset v-if="dialog.mode === 'rule' || preview && !preview.references.length" :disabled="busy" class="publisher-rule">
        <legend>{{ dialog.mode === 'purge' ? '删除后的收录规则' : '避免未来收录' }}</legend>
        <n-checkbox v-for="source in (['all', ...indirect] as Source[])" :key="source" :checked="blocked.includes(source)" :disabled="disabledSource(source)" :aria-disabled="disabledSource(source)" @update:checked="toggle(source, $event)">{{ labels[source] }}</n-checkbox>
        <p class="hint">不勾选即不屏蔽。规则适用于监控和手动导入，不影响已有帖子。</p>
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
.publisher-list { container: publisher-list / inline-size; }
.publisher-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.publisher-list .publisher-direct { display: none; }
@container publisher-list (min-width: 40rem) {
  .publisher-list .publisher-direct { display: inline-flex; }
  .publisher-list .publisher-more { display: none; }
}
@container publisher-list (max-width: 21rem) {
  .publisher-list li { grid-template-columns: minmax(0, 1fr); justify-items: start; gap: 4px; }
}
.publisher-list p { margin: 4px 0 0; }
.publisher-actions { justify-content: flex-end; }
.publisher-actions a:hover { text-decoration: none; }
.publisher-dialog { width: min(520px, calc(100vw - 32px)); max-height: 90dvh; overflow-y: auto; }
.publisher-dialog strong { overflow-wrap: anywhere; }
.publisher-dialog .n-alert { margin-top: 12px; }
.publisher-rule { padding: 0; border: 0; margin: 20px 0 0; }
.publisher-rule legend { font-weight: 600; margin-bottom: 8px; }
.publisher-rule .n-checkbox { margin-right: 16px; }
.publisher-references li { margin: 8px 0; }
.publisher-references img { width: 48px; height: 48px; object-fit: contain; }
@media (max-width: 640px) { .publisher-toolbar { gap: 8px; } .publisher-toolbar :deep(.n-radio-button) { padding-inline: 7px; } }
@media (pointer: coarse) { .publisher-rule .n-checkbox { min-height: 44px; display: inline-flex; align-items: center; } }
</style>
