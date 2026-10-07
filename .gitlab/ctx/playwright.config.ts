import { defineConfig } from '@playwright/test';

// Application foundation supplies the root package lock, start:test and browser tests.
// This runner serves the checked-out candidate; arbitrary preview URLs are not accepted.
export default defineConfig({
  testDir: '../../tests/browser',
  outputDir: '../../.ctx/browser/test-results',
  forbidOnly: true,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  reporter: [
    ['list'],
    ['junit', { outputFile: '../../.ctx/browser/junit.xml' }],
    ['html', { outputFolder: '../../.ctx/browser/html', open: 'never' }],
    ['./browser-reporter.ts'],
  ],
  use: {
    browserName: 'chromium',
    baseURL: 'http://127.0.0.1:4173',
    headless: true,
    screenshot: 'on',
    trace: 'on',
  },
  webServer: {
    command: 'npm run start:test',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
