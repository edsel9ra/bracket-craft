import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

/**
 * Arnés E2E del reintento manual del tiempo real (spec 010).
 *
 * Un solo motor (Chromium headless), una sola vista a la vez y sin reintentos:
 * el veredicto lo da `e2e/run.ts` a partir de los resultados por vista, nunca
 * un reintento que acaba en verde (RNF-002, RNF-007, RNF-008).
 *
 * Artefactos: los del arnés viven en `e2e-report/` (ignorado). Playwright deja
 * sus trazas desactivadas por defecto porque `trace.zip` incrusta cabeceras con
 * cookies; el arnés escribe su propia traza sin cabeceras (RF-005, decisión 9).
 * El estado de sesión se guarda en `.auth/state.json`, fuera de los artefactos
 * publicados y también ignorado por git.
 */

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';
const storageState = fileURLToPath(new URL('./.auth/state.json', import.meta.url));

export default defineConfig({
  testDir: './e2e',
  outputDir: fileURLToPath(new URL('./test-results', import.meta.url)),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['./e2e/reporter.ts']],
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /session\.setup\.ts/,
    },
    {
      name: 'public',
      testMatch: /realtime-public\.spec\.ts/,
      dependencies: ['setup'],
      use: { storageState },
    },
    {
      name: 'workspace',
      testMatch: /realtime-workspace\.spec\.ts/,
      dependencies: ['setup'],
      use: { storageState },
    },
    {
      name: 'operation',
      testMatch: /realtime-operation\.spec\.ts/,
      dependencies: ['setup'],
      use: { storageState },
    },
  ],
});
