import { expect, type Page, type TestInfo } from '@playwright/test';
import { createRequire } from 'node:module';
import type { AxeResults } from 'axe-core';
import { writeJsonReport } from './artifacts.ts';

const require = createRequire(import.meta.url);

export async function waitThemeHydration(page: Page) {
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
}

export async function chooseTheme(page: Page, value: 'dark' | 'light' | 'system') {
  const select = page.locator('.theme-switcher select:visible');
  const toggle = page.locator('.workspace-menu-toggle');
  if (await toggle.isVisible() && await select.count() === 0) await toggle.click();
  await expect(select).toBeVisible();
  await select.selectOption(value);
  await expect(page.locator('html')).toHaveAttribute('data-theme', value);
}

export async function assertTheme(page: Page, preference: string, scheme: string) {
  await expect(page.locator('html')).toHaveAttribute('data-theme', preference);
  await expect.poll(() => page.locator('html').evaluate(element => getComputedStyle(element).colorScheme)).toBe(scheme);
}

export async function saveThemeEvidence(info: TestInfo, name: string, value: unknown) {
  const path = await writeJsonReport(`theme-${name}.json`, value);
  await info.attach(name, { path, contentType: 'application/json' });
}

export async function auditTheme(page: Page, info: TestInfo, name: string) {
  await page.addStyleTag({ content: '#nuxt-devtools-container,#nuxt-devtools-anchor{display:none!important}' });
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const result = await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (context: Document) => Promise<AxeResults> } }).axe;
    const { testEngine, violations, incomplete } = await axe.run(document);
    const summarize = (rules: typeof violations) => rules.map(rule => ({ id: rule.id, impact: rule.impact, nodes: rule.nodes.map(node => ({ target: node.target, summary: node.failureSummary })) }));
    return { testEngine, violations: summarize(violations), incomplete: summarize(incomplete) };
  });
  await saveThemeEvidence(info, name, result);
  expect(result.violations, name).toEqual([]);
  return result;
}
