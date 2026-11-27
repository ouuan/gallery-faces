<script setup lang="ts">
import { ja } from "./locale";
import { onMounted, watchEffect } from "vue";
import {
  NConfigProvider,
  zhCN, jaJP, dateJaJP,
  dateZhCN,
  NMessageProvider,
  NDialogProvider,
  darkTheme,
} from "naive-ui";
import { Code2, Images, Rss, Settings } from "@lucide/vue";
import { feedHref, filterOnlyQuery, fromQuery } from './filters';
import ThemePicker from './ThemePicker.vue';
import NavigationMenu from './NavigationMenu.vue';
import GalleryLinks from './GalleryLinks.vue';
import { currentPageTitle } from './page-title';
import { useLibrary } from "./store";
import { themeColors } from "./theme-colors";
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
  <n-config-provider class="site-layout" :locale="ja ? jaJP : zhCN" :date-locale="ja ? dateJaJP : dateZhCN"
    :theme="store.dark ? darkTheme : null"
    :theme-overrides="{
      common: {
        ...themeColors(store.dark),
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
          <div v-if="!ja" id="site-header-action"></div>
          <router-link class="brand" :to="ja || $route.path.startsWith('/admin') ? '/' : { path: '/', query: filterOnlyQuery(fromQuery($route.query)) }" :title="store.siteTitle" :aria-label="store.siteTitle"
            ><Images :size="23" aria-hidden="true" /><span>{{
              store.siteTitle
            }}</span></router-link
          >
          <NavigationMenu v-if="!ja && !$route.path.startsWith('/admin')" v-slot="{ drawer, close }"
            :title="$route.path === '/' ? store.siteTitle : currentPageTitle" menu="图库菜单" drawer-title="图库菜单">
            <GalleryLinks :drawer="drawer" @navigate="close" />
          </NavigationMenu>
          <div class="header-actions">
            <a v-if="!ja && !$route.path.startsWith('/admin')" class="icon-link" :href="feedHref(fromQuery($route.query))" title="订阅图库 RSS" aria-label="订阅图库 RSS"><Rss :size="18" aria-hidden="true" /></a>
            <ThemePicker />
            <router-link v-if="!ja" to="/admin/import" class="nav-link" aria-label="管理"
              ><Settings :size="18" /><span>管理</span></router-link
            >
          </div>
        </header>
        <router-view />
        <footer v-if="!ja" class="site-footer">
          <a href="https://github.com/ouuan/gallery-faces" target="_blank" rel="noopener noreferrer">
            <Code2 :size="16" aria-hidden="true" />源代码
          </a>
          <span aria-hidden="true">·</span>
          <span class="footer-credit">Made by <a href="https://ouuan.moe/about" target="_blank" rel="noopener noreferrer">ouuan</a></span>
        </footer>
      </n-dialog-provider></n-message-provider
  ></n-config-provider>
</template>
