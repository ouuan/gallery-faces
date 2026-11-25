<script lang="ts">
import { AtSign, Copy, Download, Hourglass, House, LogOut, ScanFace, Settings, Users } from '@lucide/vue';

export const adminSections = [
  { id: 'monitors', label: '发布者监控', icon: Hourglass },
  { id: 'import', label: '导入任务', icon: Download },
  { id: 'people', label: '人物与分组', icon: Users },
  { id: 'review', label: '识别审核', icon: ScanFace },
  { id: 'duplicates', label: '重复图片', icon: Copy },
  { id: 'publishers', label: '未关联发布者', icon: AtSign },
  { id: 'settings', label: '设置', icon: Settings },
];
</script>

<script setup lang="ts">
defineProps<{ section: string; drawer?: boolean }>();
defineEmits<{ logout: []; navigate: [] }>();
</script>

<template>
  <nav class="admin-nav" :class="{ 'drawer-nav': drawer }" aria-label="管理页面">
    <p v-if="!drawer" class="nav-title">管理工作台</p>
    <div class="nav-links">
      <router-link v-if="drawer" to="/" @click="$emit('navigate')">
        <House :size="19" aria-hidden="true" />图库
      </router-link>
      <router-link v-for="item in adminSections" :key="item.id" :to="'/admin/' + item.id"
        :aria-current="section === item.id ? 'page' : undefined" @click="$emit('navigate')">
        <component :is="item.icon" :size="19" aria-hidden="true" />{{ item.label }}
      </router-link>
    </div>
    <button type="button" aria-label="退出登录" title="退出登录" @click="$emit('logout')">
      <LogOut :size="19" aria-hidden="true" /><span>退出登录</span>
    </button>
  </nav>
</template>

<style scoped>
.admin-nav {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 24px 12px;
  border-right: 1px solid var(--line);
  background: var(--panel);
}
.nav-title { padding: 4px 12px 20px; font-weight: 650; }
.nav-links { display: flex; flex-direction: column; gap: 4px; margin-bottom: 24px; }
a, button {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 8px 12px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--muted);
  text-decoration: none;
}
button { width: 100%; margin-top: auto; }
a:hover, button:hover { background: var(--bg); }
a[aria-current='page'] { background: var(--selection); color: var(--accent); font-weight: 600; }
.drawer-nav { min-height: 100%; padding: 12px; border: none; }
@media (min-width: 721px) and (min-height: 601px) {
  .admin-nav {
    position: sticky;
    top: var(--site-header-height);
    max-height: calc(100dvh - var(--site-header-height));
    overflow-y: auto;
  }
}
@media (min-width: 721px) and (max-height: 600px) {
  .admin-nav {
    flex-direction: row;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    border: 0;
    border-bottom: 1px solid var(--line);
  }
  .nav-title, a svg, button span { display: none; }
  .nav-links {
    flex: 1;
    flex-direction: row;
    margin-bottom: 0;
    overflow-x: auto;
    scrollbar-width: thin;
  }
  a { flex: none; white-space: nowrap; }
  a:focus-visible { outline-offset: -2px; }
  button { flex: 0 0 44px; justify-content: center; width: auto; margin: 0; }
}
</style>
