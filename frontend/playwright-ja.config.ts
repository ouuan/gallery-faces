import { defineConfig } from '@playwright/test';
import { mkdirSync } from 'node:fs';
mkdirSync('/tmp/gallery-faces', { recursive: true });
export default defineConfig({
  testDir: './tests/ja', workers: 1,
  use: { actionTimeout: 5000, baseURL: 'http://127.0.0.1:5174', headless: true, launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {} },
  webServer: { command: 'pnpm exec vite preview --mode ja --host 127.0.0.1 --port 5174 --strictPort', url: 'http://127.0.0.1:5174', reuseExistingServer: !process.env.CI },
});
