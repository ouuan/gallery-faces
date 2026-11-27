<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import { NDrawer, NDrawerContent } from 'naive-ui';
import { Menu } from '@lucide/vue';
import { useRoute } from 'vue-router';

defineProps<{ title: string; menu: string; drawerTitle: string }>();
const route = useRoute();
const media = matchMedia('(max-width: 720px)');
const compact = ref(media.matches);
const open = ref(false);
function resize() {
  compact.value = media.matches;
  open.value = false;
}
media.addEventListener('change', resize);
onUnmounted(() => media.removeEventListener('change', resize));
function close() { open.value = false; }
watch(() => route.fullPath, close);
</script>

<template>
  <template v-if="compact">
    <Teleport defer to="#site-header-action">
      <button type="button" class="drawer-trigger" aria-haspopup="dialog" :aria-expanded="open"
        :aria-label="`${menu}：${title}`" @click="open = true">
        <Menu :size="18" aria-hidden="true" /><span>{{ title }}</span>
      </button>
    </Teleport>
    <n-drawer v-model:show="open" placement="left" width="min(288px, 88vw)" :aria-label="drawerTitle">
      <n-drawer-content :title="drawerTitle" closable :body-content-style="{ padding: 0, height: '100%' }">
        <slot :drawer="true" :close="close" />
      </n-drawer-content>
    </n-drawer>
  </template>
  <slot v-else :drawer="false" :close="close" />
</template>

<style scoped>
.drawer-trigger { display: flex; align-items: center; gap: 8px; max-width: 100%; min-height: 44px; padding: 0 8px; border: 0; border-radius: 6px; color: var(--text); background: transparent; font-weight: 550; }
.drawer-trigger:hover { background: var(--bg); }
.drawer-trigger svg { flex: none; }
.drawer-trigger span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
