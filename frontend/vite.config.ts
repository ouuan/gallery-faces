import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";
export default defineConfig(({ mode }) => ({
  plugins: [vue(), {
    name: 'edition-html',
    transformIndexHtml: { order: "pre", handler(html) {
      if (mode !== 'ja') return html;
      return html.replace('lang="zh-CN"', 'lang="ja"').replace('照片库', '投稿一覧')
        .replace('/src/main.ts', '/src/main-ja.ts')
        .replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="img-src data:; media-src 'none'; object-src 'none'; frame-src https://platform.twitter.com https://platform.x.com https://syndication.twitter.com https://www.instagram.com;">`);
    } },
  }],
  build: { outDir: mode === 'ja' ? 'dist-ja' : 'dist' },
  server: { proxy: { "/api": process.env.API_PROXY_TARGET || "http://127.0.0.1:8000" } },
  test: { environment: "jsdom", include: ["tests/**/*.test.ts"] },
}));
