import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:6101' },
  webServer: [
    {
      command: 'uv run uvicorn app.main:app --port 6100',
      cwd: '../server',
      url: 'http://127.0.0.1:6100/api/jira/status',
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:6101',
      reuseExistingServer: !process.env.CI,
    },
  ],
})
