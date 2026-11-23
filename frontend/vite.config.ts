import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
import { feedHref, fromQuery } from './src/filters.ts';
export default defineConfig(({ mode, command }) => ({
  plugins: [vue(), {
    name: 'edition-html',
    transformIndexHtml: { order: "pre", async handler(html, context) {
      if (command === 'serve') {
        const page = new URL(context.originalUrl || context.path, 'http://localhost');
        if (mode !== 'ja' && page.pathname === '/') {
          const href = feedHref(fromQuery(Object.fromEntries(page.searchParams))).replaceAll('&', '&amp;');
          html = html.replace('</head>', `<link id="gallery-rss" rel="alternate" type="application/rss+xml" title="订阅图库 RSS" href="${href}"></head>`);
        }
        try {
          const origin = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
          const response = await fetch(`${origin}/api/v1/site/open-graph?locale=${mode === 'ja' ? 'ja' : 'zh'}`, { signal: AbortSignal.timeout(2000) });
          if (response.ok) html = html.replace('<!--open-graph-->', await response.text());
        } catch { /* The UI can still load while the development API is offline. */ }
      } else if (mode === 'ja') {
        html = html.replace('<!--open-graph-->', '<!--# include virtual="/api/v1/site/open-graph?locale=ja" -->');
      }
      if (mode !== 'ja') return html;
      return html.replace('lang="zh-CN"', 'lang="ja"').replace('照片库', '投稿一覧')
        .replace('/src/main.ts', '/src/main-ja.ts')
        .replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="img-src data:; media-src 'none'; object-src 'none'; frame-src https://platform.twitter.com https://platform.x.com https://syndication.twitter.com https://www.instagram.com;">`);
    } },
  }],
  build: { outDir: mode === 'ja' ? 'dist-ja' : 'dist' },
  server: { proxy: { "/api": { target: process.env.API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: false } } },
  test: { environment: "jsdom", include: ["tests/**/*.test.ts"] },
}));
