import { defineConfig } from '@playwright/test';

export default defineConfig({
  outputDir: '../test-results/theme-audit',
  testDir: '.', testMatch: /theme-(audit|capture)\.spec\.ts/, workers: 1, retries: 0, timeout: 240_000,
  use: { browserName: 'chromium', headless: true, trace: 'off', video: 'off', screenshot: 'off',
    launchOptions: { args: ['--disable-gpu', '--force-color-profile=srgb', '--force-device-scale-factor=2'] } },
});
