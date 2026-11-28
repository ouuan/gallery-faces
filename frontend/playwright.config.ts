import { mkdirSync } from "node:fs";
mkdirSync("/tmp/gallery-faces", { recursive: true });
import { defineConfig } from "@playwright/test";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:5183";
const apiOrigin = "http://127.0.0.1:8013";
export default defineConfig({
  testDir: "./tests/e2e",
  webServer: process.env.PLAYWRIGHT_BASE_URL ? undefined : [
    {
      cwd: "../backend",
      command: ".venv/bin/python -m tests.serve_workflow_fixture",
      url: `${apiOrigin}/api/v1/health`,
      gracefulShutdown: { signal: "SIGINT", timeout: 5000 },
    },
    {
      command: "pnpm exec vite --host 127.0.0.1 --port 5183 --strictPort",
      env: { API_PROXY_TARGET: apiOrigin },
      url: baseURL,
    },
  ],
  use: {
    baseURL,
    headless: true,
    launchOptions: process.env.CHROMIUM_PATH
      ? { executablePath: process.env.CHROMIUM_PATH }
      : {},
  },
  workers: 1,
  reporter: "list",
});
