<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue';
import { NDrawer, NDrawerContent } from 'naive-ui';
import { Menu } from '@lucide/vue';
import AdminNavigation from './AdminNavigation.vue';

const props = defineProps<{ section: string; title: string }>();
defineEmits<{ logout: [] }>();
const media = matchMedia('(max-width: 720px)');
const compact = ref(media.matches);
const open = ref(false);
function resize() {
  compact.value = media.matches;
  open.value = false;
}
media.addEventListener('change', resize);
onUnmounted(() => media.removeEventListener('change', resize));
watch(() => props.section, () => { open.value = false; });
</script>

<template>
  <template v-if="compact">
    <Teleport to="#admin-header-action">
      <button type="button" class="admin-trigger" aria-haspopup="dialog" :aria-expanded="open"
        :aria-label="`管理菜单：${title}`" @click="open = true">
        <Menu :size="18" aria-hidden="true" />{{ title }}
      </button>
    </Teleport>
    <n-drawer v-model:show="open" placement="left" width="min(288px, 88vw)" aria-label="管理工作台">
      <n-drawer-content title="管理工作台" closable :body-content-style="{ padding: 0, height: '100%' }">
        <AdminNavigation :section="section" drawer @navigate="open = false" @logout="open = false; $emit('logout')" />
      </n-drawer-content>
    </n-drawer>
  </template>
  <AdminNavigation v-else :section="section" @logout="$emit('logout')" />
</template>

<style scoped>
.admin-trigger { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 8px; border: 0; border-radius: 6px; color: var(--text); background: transparent; font-weight: 550; }
.admin-trigger:hover { background: var(--bg); }
</style>
