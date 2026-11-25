<script setup lang="ts">
import { computed } from 'vue';
import { NButton, NDropdown } from 'naive-ui';
import MoreMenuButton from './MoreMenuButton.vue';

const props = defineProps<{ platform: string; usernames: string[]; posts: boolean; purge: boolean }>();
defineEmits<{ open: [mode: 'rule' | 'purge'] }>();
const review = computed(() => ({ path: '/admin/review', query: { state: 'all', publishers: props.usernames.map(name => `${props.platform}:${name}`).join(',') } }));
const options = [
  { label: '设置屏蔽', key: 'rule', props: { role: 'menuitem' } },
  { label: '彻底删除帖子', key: 'purge', props: { role: 'menuitem', style: { color: 'var(--error)' } } },
];
</script>

<template>
  <div class="publisher-actions">
    <router-link v-if="posts" custom v-slot="{ href, navigate }" :to="review"><n-button tag="a" :href="href" @click="navigate">查看审核</n-button></router-link>
    <n-button :class="{ 'publisher-direct': purge }" @click="$emit('open', 'rule')">{{ posts ? '设置屏蔽' : '编辑规则' }}</n-button>
    <template v-if="purge">
      <n-button class="publisher-direct" ghost type="error" :theme-overrides="{ borderError: '1px solid var(--line)' }" @click="$emit('open', 'purge')">彻底删除帖子</n-button>
      <n-dropdown trigger="click" placement="bottom-end" :options="options" :menu-props="() => ({ role: 'menu' })" @select="key => $emit('open', key)">
        <MoreMenuButton class="publisher-more" :label="usernames.length === 1 ? `更多操作 @${usernames[0]}` : '更多批量操作'" />
      </n-dropdown>
    </template>
  </div>
</template>

<style scoped>
.publisher-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.publisher-actions a:hover { text-decoration: none; }
.publisher-direct { display: none; }
@container publisher-list (min-width: 40rem) {
  .publisher-direct { display: inline-flex; }
  .publisher-more { display: none; }
}
</style>
