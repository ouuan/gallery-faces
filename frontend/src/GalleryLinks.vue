<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { CalendarDays, Grid2x2, History, House, ScanFace, Settings, Shuffle } from '@lucide/vue';
import { filterOnlyQuery, fromQuery } from './filters';

defineProps<{ drawer: boolean }>();
defineEmits<{ navigate: [] }>();
const route = useRoute();
const filter = computed(() => fromQuery(route.query));
const query = computed(() => filterOnlyQuery(filter.value));
const items = [
  { path: '/heatmap', name: '热力图', icon: Grid2x2 },
  { path: '/daily', name: '每日一图', icon: CalendarDays }, { path: '/random', name: '随机图片', icon: Shuffle },
  { path: '/face-game', name: '认脸游戏', icon: ScanFace }, { path: '/history-quiz', name: '史官测验', icon: History },
];
</script>

<template>
  <nav class="gallery-nav" aria-label="图库导航">
    <router-link v-if="drawer" :to="{ path: '/', query }" @click="$emit('navigate')"><House :size="19" aria-hidden="true" />图库</router-link>
    <router-link v-for="item in items" :key="item.path" :to="{ path: item.path, query }" :title="item.name" :aria-label="item.name"
      :aria-current="route.path === item.path || route.path.startsWith(item.path + '/') ? 'page' : undefined" @click="$emit('navigate')">
      <component :is="item.icon" :size="drawer ? 19 : 18" aria-hidden="true" /><span>{{ item.name }}</span>
    </router-link>
    <router-link v-if="drawer" class="admin-link" to="/admin/import" @click="$emit('navigate')"><Settings :size="19" aria-hidden="true" />管理</router-link>
  </nav>
</template>

<style scoped>
.gallery-nav, a { display: flex; align-items: center; }
.gallery-nav { gap: 2px; }
a { gap: 6px; min-height: 44px; padding: 0 8px; color: var(--muted); white-space: nowrap; border-radius: 6px; }
a:hover { background: var(--bg); }
a[aria-current=page] { color: var(--accent); background: var(--selection); }
@media (min-width: 721px) and (max-width: 980px) { a { width: 44px; justify-content: center; } a span { display: none; } }
@media (max-width: 720px) {
  .gallery-nav { min-height: 100%; align-items: stretch; flex-direction: column; gap: 4px; padding: 12px; }
  .admin-link { margin-top: auto; }
  a { gap: 10px; padding: 8px 12px; text-decoration: none; }
  a[aria-current=page] { font-weight: 600; }
}
</style>
