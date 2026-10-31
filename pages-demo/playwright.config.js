import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests-browser',
  testMatch: '**/*.browser.js',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:4187/FloodHUBnepal/', browserName: 'chromium', channel: process.env.CI ? undefined : 'chrome', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: { command: 'npm run preview -- --base /FloodHUBnepal/ --host 127.0.0.1 --port 4187 --strictPort', url: 'http://127.0.0.1:4187/FloodHUBnepal/', reuseExistingServer: !process.env.CI },
})
