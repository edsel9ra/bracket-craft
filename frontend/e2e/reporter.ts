/**
 * Reporter propio del arnés E2E (`results.json`).
 *
 * Playwright no expone un resultado por vista con la clasificación de la spec
 * (verde, comportamiento, infraestructura, inválida): esa decisión la toma el
 * runner leyendo los artefactos. Este reporter solo vuelca lo que solo
 * Playwright sabe —qué proyecto se ejecutó, si terminó y cuánto tardó— para que
 * el runner pueda distinguir una vista omitida de una que falló, y un fallo del
 * test de una preparación caída.
 *
 * No se escribe ni el título del test ni el mensaje de error: así `results.json`
 * no puede arrastrar cookies, tokens ni datos de la cuenta ficticia.
 */

import type {
  FullConfig,
  FullResult,
  Reporter,
  Suite,
  TestCase,
  TestResult,
} from '@playwright/test/reporter';

import { writeJsonReport } from './artifacts.ts';
import type { PlaywrightStatus } from './runModel.ts';

/** Gravedad usada para agregar varios tests del mismo proyecto. */
const STATUS_SEVERITY: Readonly<Record<TestResult['status'], number>> = {
  passed: 0,
  skipped: 1,
  interrupted: 2,
  timedOut: 3,
  failed: 4,
};

function worseStatus(
  current: PlaywrightStatus,
  next: TestResult['status'],
): PlaywrightStatus {
  if (current === 'missing') return next;
  return STATUS_SEVERITY[next] > STATUS_SEVERITY[current] ? next : current;
}

interface ProjectAccumulator {
  status: PlaywrightStatus;
  durationMs: number;
  tests: number;
}

export default class RunReporter implements Reporter {
  private readonly projects = new Map<string, ProjectAccumulator>();

  onBegin(_config: FullConfig, _suite: Suite): void {
    // Sin estado previo: cada invocación escribe un único `results.json`.
    this.projects.clear();
  }

  onTestEnd(test: TestCase, result: TestResult): void {
    const project = test.parent.project()?.name;
    if (!project) return;

    const entry = this.projects.get(project) ?? {
      status: 'missing' as PlaywrightStatus,
      durationMs: 0,
      tests: 0,
    };
    this.projects.set(project, {
      status: worseStatus(entry.status, result.status),
      durationMs: entry.durationMs + result.duration,
      tests: entry.tests + 1,
    });
  }

  async onEnd(result: FullResult): Promise<void> {
    await writeJsonReport('results.json', {
      schemaVersion: 1,
      status: result.status,
      durationMs: result.duration,
      projects: [...this.projects.entries()].map(([project, entry]) => ({
        project,
        status: entry.status,
        durationMs: entry.durationMs,
        tests: entry.tests,
      })),
    });
  }
}
