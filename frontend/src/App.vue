<script setup lang="ts">
import { onMounted, watchEffect } from "vue";
import {
  NConfigProvider,
  zhCN,
  dateZhCN,
  NMessageProvider,
  NDialogProvider,
  darkTheme,
  NSelect,
} from "naive-ui";
import { Code2, Images, Settings } from "@lucide/vue";
import { useLibrary } from "./store";
const store = useLibrary();
onMounted(() => {
  void store.loadSite().catch(() => {});
});
watchEffect(
  () =>
    (document.documentElement.dataset.theme = store.dark ? "dark" : "light"),
);
</script>
<template>
  <n-config-provider class="site-layout" :locale="zhCN" :date-locale="dateZhCN"
    :theme="store.dark ? darkTheme : null"
    :theme-overrides="{
      common: {
        primaryColor: store.dark ? '#85adff' : '#245ec7',
        primaryColorHover: store.dark ? '#a3c1ff' : '#1e50ab',
        primaryColorPressed: store.dark ? '#6994e8' : '#19438f',
        primaryColorSuppl: store.dark ? '#a3c1ff' : '#1e50ab',
        placeholderColor: store.dark ? '#a0a9b5' : '#68717d',
        borderRadius: '6px',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      },
      Button: { heightMedium: '44px' },
      Input: { heightMedium: '44px' },
      Select: { peers: { InternalSelection: { heightMedium: '44px' } } },
      Cascader: { peers: { InternalSelection: { heightMedium: '44px' } } },
    }"
    ><n-message-provider
      ><n-dialog-provider>
        <header class="site-header">
          <router-link class="brand" to="/" :title="store.siteTitle"
            ><Images :size="23" /><span>{{
              store.siteTitle
            }}</span></router-link
          >
          <div class="header-actions">
            <n-select
              aria-label="主题"
              class="theme-select"
              :value="store.theme"
              @update:value="store.setTheme"
              :options="[
                { label: '跟随系统', value: 'system' },
                { label: '浅色', value: 'light' },
                { label: '深色', value: 'dark' },
              ]"
            /><router-link to="/admin/import" class="nav-link" aria-label="管理"
              ><Settings :size="18" /><span>管理</span></router-link
            >
          </div>
        </header>
        <router-view />
        <footer class="site-footer">
          <a href="https://github.com/ouuan/gallery-faces" target="_blank" rel="noopener noreferrer">
            <Code2 :size="16" aria-hidden="true" />源代码
          </a>
          <span aria-hidden="true">·</span>
          <span class="footer-credit">Made by <a href="https://ouuan.moe/about" target="_blank" rel="noopener noreferrer">ouuan</a></span>
        </footer>
      </n-dialog-provider></n-message-provider
  ></n-config-provider>
</template>
