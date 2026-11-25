<script setup lang="ts">
import { computed, h, ref } from 'vue';
import { NButton, NDropdown } from 'naive-ui';
import { Monitor, Moon, Smartphone, Sun, Tablet } from '@lucide/vue';
import { t } from './locale';
import { useLibrary } from './store';

function systemIcon() {
  const { userAgent, maxTouchPoints } = navigator;
  if (/iPad|Tablet/i.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1)) return Tablet;
  if (/Mobi|iPhone|iPod/i.test(userAgent)) return Smartphone;
  if (/Android/i.test(userAgent)) return Tablet;
  return Monitor;
}

const store = useLibrary();
const open = ref(false);
const themes = [
  { key: 'system', label: t('跟随系统'), glyph: systemIcon() },
  { key: 'light', label: t('浅色'), glyph: Sun },
  { key: 'dark', label: t('深色'), glyph: Moon },
];
const options = themes.map(({ key, label, glyph }) => ({ key, label, icon: () => h(glyph, { size: 18, 'aria-hidden': true }) }));
const current = computed(() => themes.find(item => item.key === store.theme) ?? themes[0]);
const label = computed(() => `${t('主题')}：${current.value.label}`);
</script>

<template>
  <n-dropdown v-model:show="open" trigger="click" placement="bottom-end" :options="options" :value="store.theme"
    :menu-props="() => ({ role: 'menu', 'aria-label': t('主题') })"
    :node-props="item => ({ role: 'menuitemradio', 'aria-checked': item.key === store.theme ? 'true' : 'false' })" @select="store.setTheme">
    <n-button quaternary circle :title="label" :aria-label="label" aria-haspopup="menu" :aria-expanded="open">
      <template #icon><component :is="current.glyph" :size="19" aria-hidden="true" /></template>
    </n-button>
  </n-dropdown>
</template>
