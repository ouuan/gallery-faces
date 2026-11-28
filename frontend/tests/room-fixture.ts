import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { expect, test as base, type Page } from '@playwright/test';

export const test = base.extend<{ guests: Page[]; dateRange: boolean }>({
  dateRange: [false, { option: true }],
  guests: async ({ browser, baseURL, dateRange, timezoneId }, use) => {
    const server = spawn('.venv/bin/python', ['tests/serve_room_fixture.py'], { cwd: '../backend', env: { ...process.env, PYTHONPATH: '.', FIXTURE_DATE_RANGE: dateRange ? '1' : '0' }, stdio: ['ignore', 'pipe', 'inherit'] });
    const exited = new Promise(resolve => server.once('exit', resolve));
    const contexts = await Promise.all([{ width: 375, height: 667 }, { width: 1280, height: 860 }, { width: 390, height: 844 }].map(viewport => browser.newContext({ baseURL, viewport, timezoneId })));
    try {
      let origin = '';
      for await (const line of createInterface({ input: server.stdout })) {
        if (line.startsWith('ROOM_ORIGIN=')) { origin = line.slice(12); break; }
      }
      expect(origin).toBeTruthy();
      await expect.poll(async () => fetch(origin + '/api/v1/health').then(response => response.ok).catch(() => false)).toBe(true);
      for (const context of contexts) {
        await context.route('**/api/v1/**', async route => {
          const url = new URL(route.request().url());
          try { await route.fulfill({ response: await route.fetch({ url: origin + url.pathname + url.search }) }); }
          catch (error) { if (context.pages().length) throw error; }
        });
      }
      await use(await Promise.all(contexts.map(context => context.newPage())));
    } finally {
      await Promise.all(contexts.map(context => context.close()));
      server.kill(); await exited;
    }
  },
});
